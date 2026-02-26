# Invoice & Delivery Note Implementation Guide

**Document Version:** 1.0  
**Purpose:** Detailed code examples for implementing delivery note workflow enhancements  
**Target:** Developers implementing P2 and P3 phases

---

## Quick Start: What to Implement First

If you have 1 sprint, implement **P2.1 only** (standalone DN with customer/branch/items):
- Unlocks Scenario 2 (parallel invoice & DN creation)
- Prerequisite for Scenario 3 (pre-invoice DNs)
- Relatively low-risk changes (serializer + view logic)
- ~2-3 days development + 1 day QA

---

## Implementation Phase 1: Enhanced DeliveryNoteCreateSerializer

### Step 1: Define New Serializer Class

**File:** `finance/invoicing/serializers.py`

Replace the existing `DeliveryNoteCreateSerializer` (around line 395) with:

```python
from rest_framework import serializers
from django.db import transaction
from decimal import Decimal
from .models import DeliveryNote
from crm.contacts.models import Contact
from business.models import Branch
from core_orders.models import OrderItem

class OrderItemCreateSerializer(serializers.Serializer):
    """Serializer for creating order items in bulk"""
    product_id = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField(required=True, max_length=255)
    description = serializers.CharField(required=False, allow_blank=True)
    quantity = serializers.IntegerField(required=True, min_value=1)
    unit_price = serializers.DecimalField(max_digits=15, decimal_places=2, required=True)
    total_price = serializers.DecimalField(
        max_digits=15, decimal_places=2, required=False, allow_null=True
    )
    sku = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)

    def validate_unit_price(self, value):
        if value < 0:
            raise serializers.ValidationError("Unit price cannot be negative")
        return value

    def validate_quantity(self, value):
        if value <= 0:
            raise serializers.ValidationError("Quantity must be positive")
        return value


class DeliveryNoteCreateSerializer(serializers.ModelSerializer):
    """
    Serializer for creating delivery notes.
    
    Supports three creation modes:
    1. From existing invoice: POST with source_invoice_id
    2. From existing purchase order: POST with source_purchase_order_id
    3. Standalone: POST with customer_id, branch_id, and optional items
    """
    
    # Read-only: will be handled specially
    source_invoice_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    source_purchase_order_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    
    # NEW: Allow standalone DN creation with explicit customer/branch
    customer_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    branch_id = serializers.IntegerField(required=False, allow_null=True, write_only=True)
    
    # NEW: Support inline items for standalone DNs
    items = OrderItemCreateSerializer(many=True, required=False, write_only=True)
    
    delivery_address = serializers.CharField(required=False, allow_blank=True)

    class Meta:
        model = DeliveryNote
        fields = [
            'source_invoice_id', 'source_purchase_order_id',
            'customer_id', 'branch_id',
            'delivery_date',
            'delivery_address',
            'driver_name', 'driver_phone', 'vehicle_number',
            'special_instructions',
            'items'
        ]

    def validate(self, data):
        """
        Validate that either a source document is specified OR
        customer/branch are provided for standalone DN.
        """
        has_source_doc = data.get('source_invoice_id') or data.get('source_purchase_order_id')
        has_explicit_customer = data.get('customer_id')
        has_explicit_branch = data.get('branch_id')
        
        if not has_source_doc:
            # Standalone DN requires both customer and branch
            if not has_explicit_customer:
                raise serializers.ValidationError({
                    'customer_id': 'Required for standalone delivery notes'
                })
            if not has_explicit_branch:
                raise serializers.ValidationError({
                    'branch_id': 'Required for standalone delivery notes'
                })
        
        return data

    @transaction.atomic
    def create(self, validated_data):
        """
        Create delivery note with transaction rollback on any error.
        
        Three paths:
        1. FROM_INVOICE: Clone data from existing invoice
        2. FROM_PO: Clone data from existing purchase order
        3. STANDALONE: Create with explicit customer/branch/items
        """
        
        # Extract data that's not in DeliveryNote model
        items_data = validated_data.pop('items', [])
        source_invoice_id = validated_data.pop('source_invoice_id', None)
        source_purchase_order_id = validated_data.pop('source_purchase_order_id', None)
        customer_id = validated_data.pop('customer_id', None)
        branch_id = validated_data.pop('branch_id', None)
        
        request = self.context.get('request')
        user = request.user if request else None
        
        # PATH 1: Create from existing invoice
        if source_invoice_id:
            from .models import Invoice
            try:
                invoice = Invoice.objects.get(pk=source_invoice_id)
            except Invoice.DoesNotExist:
                raise serializers.ValidationError({
                    'source_invoice_id': f'Invoice with id {source_invoice_id} not found'
                })
            
            delivery_note = DeliveryNote.create_from_invoice(
                invoice,
                created_by=user,
                delivery_address=validated_data.get('delivery_address')
            )
        
        # PATH 2: Create from existing purchase order
        elif source_purchase_order_id:
            from procurement.orders.models import PurchaseOrder
            try:
                po = PurchaseOrder.objects.get(pk=source_purchase_order_id)
            except PurchaseOrder.DoesNotExist:
                raise serializers.ValidationError({
                    'source_purchase_order_id': f'Purchase order with id {source_purchase_order_id} not found'
                })
            
            delivery_note = DeliveryNote.create_from_purchase_order(
                po,
                created_by=user,
                delivery_address=validated_data.get('delivery_address')
            )
        
        # PATH 3: Create standalone DN
        else:
            # Resolve customer
            try:
                customer = Contact.objects.get(pk=customer_id)
            except Contact.DoesNotExist:
                raise serializers.ValidationError({
                    'customer_id': f'Customer with id {customer_id} not found'
                })
            
            # Resolve branch
            try:
                branch = Branch.objects.get(pk=branch_id)
            except Branch.DoesNotExist:
                raise serializers.ValidationError({
                    'branch_id': f'Branch with id {branch_id} not found'
                })
            
            # Prepare data for creation
            validated_data['customer'] = customer
            validated_data['branch'] = branch
            validated_data['created_by'] = user
            validated_data['order_type'] = 'delivery_note'
            
            # Set default financial fields for standalone DN
            if 'subtotal' not in validated_data:
                validated_data['subtotal'] = Decimal('0.00')
            if 'tax_amount' not in validated_data:
                validated_data['tax_amount'] = Decimal('0.00')
            if 'discount_amount' not in validated_data:
                validated_data['discount_amount'] = Decimal('0.00')
            if 'shipping_cost' not in validated_data:
                validated_data['shipping_cost'] = Decimal('0.00')
            if 'total' not in validated_data:
                validated_data['total'] = Decimal('0.00')
            
            # Create the delivery note
            delivery_note = DeliveryNote.objects.create(**validated_data)
            
            # Create items if provided
            if items_data:
                total = Decimal('0.00')
                for idx, item_data in enumerate(items_data):
                    # Calculate total_price if not provided
                    if not item_data.get('total_price'):
                        item_data['total_price'] = (
                            Decimal(str(item_data.get('unit_price', 0))) *
                            item_data.get('quantity', 1)
                        )
                    
                    total += item_data['total_price']
                    
                    # Create order item
                    OrderItem.objects.create(
                        order=delivery_note,
                        name=item_data.get('name'),
                        description=item_data.get('description', ''),
                        quantity=item_data.get('quantity'),
                        unit_price=item_data.get('unit_price'),
                        total_price=item_data.get('total_price'),
                        sku=item_data.get('sku', ''),
                        notes=item_data.get('notes', '')
                    )
                
                # Update DN totals based on items
                delivery_note.subtotal = total
                delivery_note.total = total  # Excluding tax/discount for now
        
        # Update additional fields (applicable to all creation paths)
        for field in ['driver_name', 'driver_phone', 'vehicle_number', 'special_instructions']:
            if field in validated_data and validated_data[field]:
                setattr(delivery_note, field, validated_data[field])
        
        delivery_note.save()
        
        # Log the creation
        from core.audit import AuditTrail
        if user:
            AuditTrail.log(
                user=user,
                action='create_delivery_note',
                object_type='DeliveryNote',
                object_id=delivery_note.id,
                details=f'Created delivery note {delivery_note.delivery_note_number}'
            )
        
        return delivery_note
```

### Step 2: Update DeliveryNoteViewSet

**File:** `finance/invoicing/views.py` (around line 1095)

Update the `get_serializer_class` method:

```python
class DeliveryNoteViewSet(BaseModelViewSet):
    # ... existing code ...
    
    def get_serializer_class(self):
        """
        Return appropriate serializer based on action.
        Use DeliveryNoteCreateSerializer for write operations.
        """
        if self.action in ['create', 'create_from_invoice', 'create_from_purchase_order']:
            return DeliveryNoteCreateSerializer
        return DeliveryNoteSerializer
```

No changes needed to the ViewSet itself — Django REST Framework will call the updated serializer.

### Step 3: Update Model to Support Totals Calculation

**File:** `finance/invoicing/models.py` (DeliveryNote.save method)

Ensure the `save()` method recalculates totals:

```python
def save(self, *args, **kwargs):
    # Set order_type
    if not self.order_type:
        self.order_type = 'delivery_note'

    # Auto-generate delivery note number
    if not self.delivery_note_number:
        self.delivery_note_number = self.generate_delivery_note_number()

    # Auto-generate order_number if not set
    if not self.order_number:
        self.order_number = self.delivery_note_number
    
    # NEW: Recalculate totals if not explicitly set
    if not self.total and self.subtotal:
        self.total = (
            self.subtotal +
            self.tax_amount -
            self.discount_amount +
            self.shipping_cost
        )

    super().save(*args, **kwargs)
```

---

## Implementation Phase 2: Add Explicit Linking Endpoint

### Step 1: Add link-to-invoice Action

**File:** `finance/invoicing/views.py`

Add this method to the `DeliveryNoteViewSet` class (add after existing action methods like `mark_delivered`):

```python
@action(detail=True, methods=['post'], url_path='link-to-invoice')
def link_invoice(self, request, pk=None):
    """
    Link an existing delivery note to an invoice.
    
    This enables post-creation association for scenarios where:
    1. DN was created before invoice(s)
    2. DN and invoice were created independently
    3. DN needs retroactive invoice association
    
    POST /api/delivery-notes/{id}/link-to-invoice/
    {
        "invoice_id": 100
    }
    """
    delivery_note = self.get_object()
    invoice_id = request.data.get('invoice_id')
    
    if not invoice_id:
        return APIResponse.bad_request(
            message="invoice_id is required",
            errors={"invoice_id": "This field is required"}
        )
    
    # Resolve invoice
    try:
        from .models import Invoice
        invoice = Invoice.objects.get(pk=invoice_id)
    except Invoice.DoesNotExist:
        return APIResponse.not_found(
            message=f"Invoice with id {invoice_id} not found"
        )
    
    # Validation 1: Both must belong to same customer
    if delivery_note.customer_id != invoice.customer_id:
        return APIResponse.bad_request(
            message="Cannot link: delivery note and invoice have different customers",
            errors={
                "customer_mismatch": (
                    f"DN customer: {delivery_note.customer_id}, "
                    f"Invoice customer: {invoice.customer_id}"
                )
            }
        )
    
    # Validation 2: Items must match if both have items
    dn_items = list(delivery_note.items.all())
    inv_items = list(invoice.items.all())
    
    if dn_items and inv_items:
        dn_item_ids = [item.id for item in dn_items]
        inv_item_ids = [item.id for item in inv_items]
        
        if dn_item_ids != inv_item_ids:
            return APIResponse.bad_request(
                message="Cannot link: item lists do not match",
                errors={
                    "items_mismatch": (
                        f"DN has {len(dn_items)} items, "
                        f"Invoice has {len(inv_items)} items"
                    )
                }
            )
    
    # Validation 3: Check for existing invoice link
    if delivery_note.source_invoice_id and delivery_note.source_invoice_id != invoice.id:
        return APIResponse.bad_request(
            message=(
                f"Cannot link: delivery note is already linked to "
                f"Invoice #{delivery_note.source_invoice.invoice_number}"
            )
        )
    
    # All validations passed — perform linking
    try:
        delivery_note.source_invoice = invoice
        delivery_note.save(update_fields=['source_invoice', 'updated_at'])
        
        # Log audit trail
        from core.audit import AuditTrail
        AuditTrail.log(
            user=request.user,
            action='link_delivery_note_to_invoice',
            object_type='DeliveryNote',
            object_id=delivery_note.id,
            details=(
                f'Linked to Invoice #{invoice.id} ({invoice.invoice_number})'
            )
        )
        
        return APIResponse.success(
            data=DeliveryNoteSerializer(delivery_note).data,
            message=(
                f'Delivery note #{delivery_note.delivery_note_number} '
                f'linked to Invoice #{invoice.invoice_number} successfully'
            )
        )
    
    except Exception as e:
        return APIResponse.error(
            message="Error linking delivery note to invoice",
            errors={"exception": str(e)}
        )
```

### Step 2: Add Complementary Unlink Action (Optional)

```python
@action(detail=True, methods=['post'], url_path='unlink-from-invoice')
def unlink_invoice(self, request, pk=None):
    """
    Unlink delivery note from an invoice.
    Useful if incorrect invoice was linked.
    """
    delivery_note = self.get_object()
    
    if not delivery_note.source_invoice:
        return APIResponse.bad_request(
            message="Delivery note is not linked to any invoice"
        )
    
    old_invoice = delivery_note.source_invoice
    delivery_note.source_invoice = None
    delivery_note.save(update_fields=['source_invoice', 'updated_at'])
    
    # Audit log
    from core.audit import AuditTrail
    AuditTrail.log(
        user=request.user,
        action='unlink_delivery_note_from_invoice',
        object_type='DeliveryNote',
        object_id=delivery_note.id,
        details=f'Unlinked from Invoice #{old_invoice.id}'
    )
    
    return APIResponse.success(
        data=DeliveryNoteSerializer(delivery_note).data,
        message='Delivery note unlinked from invoice'
    )
```

---

## Implementation Phase 3: Add Status Synchronization

### Step 1: Create Workflow Rules Module

**File:** `finance/invoicing/workflow.py` (new file)

```python
"""
Workflow rules for Invoice-DeliveryNote synchronization.

Enforces business rules:
- Invoice cannot be paid without delivered delivery note
- Cancelling invoice cascades to related DNs
- DN status influences invoice status
"""

from django.db import transaction
from django.core.exceptions import ValidationError
from decimal import Decimal


class DocumentWorkflowError(ValidationError):
    """Raised when workflow rule violated"""
    pass


class InvoiceWorkflowRules:
    """Business rules for Invoice status transitions"""
    
    # Allowed transitions between statuses
    ALLOWED_TRANSITIONS = {
        'draft': ['sent', 'cancelled', 'void'],
        'sent': ['viewed', 'cancelled', 'void'],
        'viewed': ['partially_paid', 'overdue', 'paid', 'cancelled'],
        'partially_paid': ['paid', 'overdue', 'cancelled'],
        'paid': [],  # Terminal state
        'overdue': ['paid', 'cancelled'],
        'cancelled': [],  # Terminal
        'void': [],  # Terminal
    }
    
    @classmethod
    def validate_transition(cls, current_status, new_status):
        """
        Check if transition is allowed.
        Raise DocumentWorkflowError if invalid.
        """
        allowed = cls.ALLOWED_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise DocumentWorkflowError(
                f"Cannot transition Invoice from '{current_status}' to '{new_status}'"
            )
    
    @classmethod
    @transaction.atomic
    def on_status_change(cls, invoice, new_status, old_status):
        """
        Handle side effects when invoice status changes.
        
        Rules:
        1. Draft/Sent/Viewed: No delivery note checks
        2. Partially Paid: At least one DN should exist
        3. Paid: At least one DN must be delivered
        4. Cancelled: Cascade cancel to related DNs
        5. Void: Same as cancelled
        """
        
        # Rule 1: Validate transition allowed
        cls.validate_transition(old_status, new_status)
        
        # Rule 2: If marking as paid, verify delivery
        if new_status == 'paid':
            related_dns = invoice.dn_from_invoice.all()
            
            # If invoice has delivery notes, at least one must be delivered
            if related_dns.exists():
                delivered_dns = related_dns.filter(status='delivered')
                if not delivered_dns.exists():
                    raise DocumentWorkflowError(
                        f"Cannot mark invoice as paid: "
                        f"None of {related_dns.count()} delivery notes are marked delivered"
                    )
        
        # Rule 3: If cancelling, cascade to DNs
        if new_status in ['cancelled', 'void']:
            related_dns = invoice.dn_from_invoice.all()
            for dn in related_dns:
                if dn.status not in ['cancelled']:
                    dn.status = 'cancelled'
                    dn.save(update_fields=['status', 'updated_at'])


class DeliveryNoteWorkflowRules:
    """Business rules for DeliveryNote status transitions"""
    
    ALLOWED_TRANSITIONS = {
        'draft': ['pending', 'cancelled'],
        'pending': ['in_transit', 'delivered', 'partially_delivered', 'cancelled'],
        'in_transit': ['delivered', 'partially_delivered', 'cancelled'],
        'delivered': ['partially_delivered'],  # Only regression allowed
        'partially_delivered': ['delivered', 'cancelled'],
        'cancelled': [],  # Terminal
    }
    
    @classmethod
    def validate_transition(cls, current_status, new_status):
        allowed = cls.ALLOWED_TRANSITIONS.get(current_status, [])
        if new_status not in allowed:
            raise DocumentWorkflowError(
                f"Cannot transition DeliveryNote from '{current_status}' to '{new_status}'"
            )
    
    @classmethod
    @transaction.atomic
    def on_status_change(cls, delivery_note, new_status, old_status):
        """
        Handle side effects when delivery note status changes.
        
        Rules:
        1. Draft/Pending: No invoice interactions
        2. In Transit: Invoice should reflect active delivery
        3. Delivered: If invoice linked, mark viewed (payable)
        4. Partially Delivered: Warn if payment expected
        5. Cancelled: If invoice linked, revert to viewed
        """
        
        # Rule 1: Validate transition
        cls.validate_transition(old_status, new_status)
        
        # Rule 2: Sync with associated invoice (if exists)
        if not delivery_note.source_invoice:
            return
        
        invoice = delivery_note.source_invoice
        related_dns = invoice.dn_from_invoice.all()
        
        # Rule 3: When DN marked delivered, check if all related DNs delivered
        if new_status == 'delivered':
            all_delivered = all(
                dn.status == 'delivered' for dn in related_dns
            )
            
            if all_delivered and invoice.status not in ['paid', 'cancelled', 'void']:
                # All goods delivered, mark invoice as viewed (ready for payment)
                invoice.status = 'viewed'
                invoice.save(update_fields=['status', 'updated_at'])
        
        # Rule 4: When DN cancelled, potentially revert invoice
        elif new_status == 'cancelled':
            # If all DNs are cancelled, mark invoice as viewed
            all_cancelled = all(
                dn.status == 'cancelled' for dn in related_dns
            )
            
            if all_cancelled and invoice.status not in ['paid', 'cancelled', 'void']:
                invoice.status = 'viewed'  # Can re-fulfill
                invoice.save(update_fields=['status', 'updated_at'])
        
        # Rule 5: When DN partially delivered, update invoice status
        elif new_status == 'partially_delivered':
            if invoice.status == 'draft':
                invoice.status = 'viewed'
                invoice.save(update_fields=['status', 'updated_at'])


def check_invoice_payment_permission(invoice, amount_to_pay):
    """
    Check if invoice can be paid.
    
    Business rules:
    - Cannot pay invoice with cancelled DNs
    - Payment amount cannot exceed balance due
    - If payment amount high, require delivery confirmation
    """
    
    related_dns = invoice.dn_from_invoice.all()
    
    # Rule 1: All DNs should not be cancelled
    cancelled_dns = related_dns.filter(status='cancelled')
    if cancelled_dns.exists() and related_dns.count() == cancelled_dns.count():
        raise DocumentWorkflowError(
            "Cannot pay invoice: all associated delivery notes are cancelled"
        )
    
    # Rule 2: Payment amount validation
    amount_to_pay = Decimal(str(amount_to_pay))
    if amount_to_pay > invoice.balance_due:
        raise DocumentWorkflowError(
            f"Payment amount ${amount_to_pay} exceeds balance due ${invoice.balance_due}"
        )
    
    return True
```

### Step 2: Integrate Workflow Rules into Models

**File:** `finance/invoicing/models.py`

Update the `Invoice.save()` method:

```python
def save(self, *args, **kwargs):
    # ... existing code ...
    
    # NEW: Validate status transitions
    if self.pk:  # Only on updates
        old_instance = Invoice.objects.get(pk=self.pk)
        if old_instance.status != self.status:
            from .workflow import InvoiceWorkflowRules
            InvoiceWorkflowRules.on_status_change(
                self, self.status, old_instance.status
            )
    
    super().save(*args, **kwargs)
```

Update the `DeliveryNote.save()` method:

```python
def save(self, *args, **kwargs):
    # ... existing code ...
    
    # NEW: Validate status transitions
    if self.pk:  # Only on updates
        old_instance = DeliveryNote.objects.get(pk=self.pk)
        if old_instance.status != self.status:
            from .workflow import DeliveryNoteWorkflowRules
            DeliveryNoteWorkflowRules.on_status_change(
                self, self.status, old_instance.status
            )
    
    super().save(*args, **kwargs)
```

### Step 3: Update mark_delivered() Method

**File:** `finance/invoicing/models.py`

Update the `DeliveryNote.mark_delivered()` method:

```python
def mark_delivered(self, received_by=None, notes=None):
    """Mark delivery note as delivered with validation"""
    from django.utils import timezone
    from .workflow import DeliveryNoteWorkflowRules
    
    # Validate transition
    DeliveryNoteWorkflowRules.validate_transition(self.status, 'delivered')
    
    self.status = 'delivered'
    self.received_by = received_by or self.received_by
    self.received_at = timezone.now()
    
    # This will trigger on_status_change via save()
    self.save()
```

---

## Testing Implementation

### Test File: `finance/invoicing/tests/test_delivery_note_creation.py`

```python
from django.test import TestCase, Client
from django.contrib.auth import get_user_model
from crm.contacts.models import Contact
from business.models import Business, Branch
from finance.invoicing.models import DeliveryNote, Invoice
from core_orders.models import OrderItem
from rest_framework.test import APIClient
from rest_framework import status
from decimal import Decimal

User = get_user_model()


class CreateStandaloneDeliveryNoteTests(TestCase):
    """Tests for P2.1: Standalone delivery note with customer/branch/items"""
    
    @classmethod
    def setUpTestData(cls):
        """Setup test data - runs once for entire test class"""
        # Create user
        cls.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        
        # Create business and branch
        cls.business = Business.objects.create(
            owner=cls.user,
            business_name='Test Business'
        )
        cls.branch = Branch.objects.create(
            business=cls.business,
            branch_name='Main Branch',
            branch_code='MB001'
        )
        
        # Create customer contact
        cls.customer = Contact.objects.create(
            user=cls.user,
            business_name='Customer Ltd',
            contact_type='customer'
        )
    
    def setUp(self):
        """Setup for each test"""
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
    
    def test_create_standalone_dn_without_items(self):
        """Test creating standalone DN with just customer/branch/delivery details"""
        response = self.client.post(
            '/api/delivery-notes/',
            {
                'customer_id': self.customer.id,
                'branch_id': self.branch.id,
                'delivery_address': '123 Main St, Nairobi',
                'driver_name': 'John Doe',
                'driver_phone': '0700123456',
                'vehicle_number': 'KCG 456A',
                'special_instructions': 'Ring bell twice'
            },
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertIn('delivery_note_number', response.data)
        self.assertIsNone(response.data.get('source_invoice'))
        
        # Verify in database
        dn = DeliveryNote.objects.get(id=response.data['id'])
        self.assertEqual(dn.customer_id, self.customer.id)
        self.assertEqual(dn.branch_id, self.branch.id)
        self.assertEqual(dn.driver_name, 'John Doe')
        self.assertEqual(dn.status, 'draft')
    
    def test_create_standalone_dn_with_items(self):
        """Test creating standalone DN with embedded items"""
        response = self.client.post(
            '/api/delivery-notes/',
            {
                'customer_id': self.customer.id,
                'branch_id': self.branch.id,
                'delivery_address': '123 Main St',
                'items': [
                    {
                        'name': 'Product A',
                        'quantity': 5,
                        'unit_price': Decimal('100.00'),
                        'description': 'Test product A'
                    },
                    {
                        'name': 'Product B',
                        'quantity': 3,
                        'unit_price': Decimal('50.00')
                    }
                ]
            },
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # Verify items created
        dn = DeliveryNote.objects.get(id=response.data['id'])
        self.assertEqual(dn.items.count(), 2)
        
        items = list(dn.items.all())
        self.assertEqual(items[0].name, 'Product A')
        self.assertEqual(items[0].quantity, 5)
        self.assertEqual(items[1].name, 'Product B')
        self.assertEqual(items[1].quantity, 3)
    
    def test_create_standalone_dn_without_customer_fails(self):
        """Test that standalone DN requires customer_id"""
        response = self.client.post(
            '/api/delivery-notes/',
            {
                'branch_id': self.branch.id,
                'delivery_address': '123 Main St'
                # Missing customer_id
            },
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('customer_id', response.data.get('errors', {}))
    
    def test_create_dn_from_invoice_ignores_customer_param(self):
        """Test that source_invoice takes precedence over customer_id"""
        # Create an invoice first
        invoice = Invoice.objects.create(
            customer=self.customer,
            branch=self.branch,
            subtotal=Decimal('1000.00'),
            total=Decimal('1000.00')
        )
        
        # Create another customer
        other_customer = Contact.objects.create(
            user=self.user,
            business_name='Other Customer',
            contact_type='customer'
        )
        
        # Try to create DN from invoice with different customer
        response = self.client.post(
            '/api/delivery-notes/create-from-invoice/',
            {
                'source_invoice_id': invoice.id,
                'customer_id': other_customer.id,  # Will be ignored
                'delivery_address': 'New Address'
            },
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        
        # DN should have invoice's customer, not the supplied one
        dn = DeliveryNote.objects.get(id=response.data['id'])
        self.assertEqual(dn.customer_id, invoice.customer_id)
        self.assertNotEqual(dn.customer_id, other_customer.id)


class LinkDeliveryNoteToInvoiceTests(TestCase):
    """Tests for P2.2: Explicit linking endpoint"""
    
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email='test@example.com',
            password='testpass123'
        )
        cls.business = Business.objects.create(
            owner=cls.user,
            business_name='Test Business'
        )
        cls.branch = Branch.objects.create(
            business=cls.business,
            branch_name='Main Branch'
        )
        cls.customer = Contact.objects.create(
            user=cls.user,
            business_name='Customer Ltd',
            contact_type='customer'
        )
    
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
    
    def test_link_standalone_dn_to_invoice(self):
        """Test linking a pre-created DN to an invoice"""
        # Create standalone DN
        dn = DeliveryNote.objects.create(
            customer=self.customer,
            branch=self.branch,
            delivery_address='123 Main St',
            driver_name='John'
        )
        
        # Create invoice
        invoice = Invoice.objects.create(
            customer=self.customer,
            branch=self.branch,
            subtotal=Decimal('1000.00'),
            total=Decimal('1000.00')
        )
        
        # Link DN to invoice
        response = self.client.post(
            f'/api/delivery-notes/{dn.id}/link-to-invoice/',
            {'invoice_id': invoice.id},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        
        # Verify linking
        dn.refresh_from_db()
        self.assertEqual(dn.source_invoice_id, invoice.id)
    
    def test_cannot_link_different_customer_dn_to_invoice(self):
        """Test that DN and Invoice must have same customer"""
        customer1 = self.customer
        customer2 = Contact.objects.create(
            user=self.user,
            business_name='Other Customer',
            contact_type='customer'
        )
        
        # DN with customer1
        dn = DeliveryNote.objects.create(
            customer=customer1,
            branch=self.branch,
            delivery_address='123 Main St'
        )
        
        # Invoice with customer2
        invoice = Invoice.objects.create(
            customer=customer2,
            branch=self.branch,
            subtotal=Decimal('1000.00'),
            total=Decimal('1000.00')
        )
        
        # Try to link
        response = self.client.post(
            f'/api/delivery-notes/{dn.id}/link-to-invoice/',
            {'invoice_id': invoice.id},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn('customer_mismatch', response.data.get('errors', {}))
    
    def test_cannot_relink_dn_to_different_invoice(self):
        """Test that DN cannot be relinked to a different invoice"""
        invoice1 = Invoice.objects.create(
            customer=self.customer,
            branch=self.branch,
            subtotal=Decimal('1000.00'),
            total=Decimal('1000.00')
        )
        
        invoice2 = Invoice.objects.create(
            customer=self.customer,
            branch=self.branch,
            subtotal=Decimal('500.00'),
            total=Decimal('500.00')
        )
        
        # DN already linked to invoice1
        dn = DeliveryNote.objects.create(
            customer=self.customer,
            branch=self.branch,
            source_invoice=invoice1
        )
        
        # Try to link to invoice2
        response = self.client.post(
            f'/api/delivery-notes/{dn.id}/link-to-invoice/',
            {'invoice_id': invoice2.id},
            format='json'
        )
        
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
```

---

## Integration Testing: Pre-Invoice DN Workflow

Create test: `finance/invoicing/tests/test_pre_invoice_workflow.py`

```python
from django.test import TestCase
from datetime import datetime, timedelta
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from crm.contacts.models import Contact
from business.models import Business, Branch
from finance.invoicing.models import DeliveryNote, Invoice
from decimal import Decimal

User = get_user_model()


class PreInvoiceDeliveryNoteWorkflowTest(TestCase):
    """
    Integration test for Scenario 3: Pre-Invoice Delivery Note Workflow
    
    This test demonstrates the complete workflow:
    T1: Create DN and send to customer (advance notification)
    T2: Goods in transit
    T3: Goods delivered, customer confirms in DN
    T4: Create invoice referencing DN
    T5: Customer receives invoice
    """
    
    @classmethod
    def setUpTestData(cls):
        cls.user = User.objects.create_user(
            email='warehouse@bengobox.co.ke',
            password='pass123'
        )
        cls.business = Business.objects.create(
            owner=cls.user,
            business_name='Bengobox'
        )
        cls.branch = Branch.objects.create(
            business=cls.business,
            branch_name='Warehouse'
        )
        cls.customer = Contact.objects.create(
            user=cls.user,
            business_name='Hospital Inc',
            contact_type='customer'
        )
    
    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(user=self.user)
    
    def test_pre_invoice_delivery_workflow(self):
        """
        Test the complete pre-invoice DN workflow
        """
        
        # STEP 1: Create Delivery Note (advance notification)
        print("\n=== STEP 1: Create Standalone DN ===")
        dn_response = self.client.post(
            '/api/delivery-notes/',
            {
                'customer_id': self.customer.id,
                'branch_id': self.branch.id,
                'delivery_date': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
                'delivery_address': 'Hospital Main Gate, Nairobi',
                'driver_name': 'Samuel Kipchoge',
                'vehicle_number': 'KCG 234M',
                'items': [
                    {
                        'name': 'Medical Supplies Box A',
                        'quantity': 50,
                        'unit_price': Decimal('500.00')
                    },
                    {
                        'name': 'Sterile Gloves',
                        'quantity': 100,
                        'unit_price': Decimal('50.00')
                    }
                ]
            },
            format='json'
        )
        
        self.assertEqual(dn_response.status_code, 201)
        dn_data = dn_response.data
        dn_id = dn_data['id']
        dn_number = dn_data['delivery_note_number']
        print(f"✓ Created DN #{dn_number} (ID: {dn_id})")
        print(f"  - Status: {dn_data['status']}")
        print(f"  - Items: {dn_data['items__count']} items")
        print(f"  - Total: {dn_data.get('total', 'N/A')}")
        
        # STEP 2: Confirm goods in transit
        print("\n=== STEP 2: Mark DN as In Transit ===")
        transit_response = self.client.patch(
            f'/api/delivery-notes/{dn_id}/',
            {'status': 'in_transit'},
            format='json'
        )
        self.assertEqual(transit_response.status_code, 200)
        print(f"✓ DN status: {transit_response.data['status']}")
        
        # STEP 3: Confirm delivery
        print("\n=== STEP 3: Mark DN as Delivered ===")
        delivered_response = self.client.post(
            f'/api/delivery-notes/{dn_id}/mark-delivered/',
            {
                'received_by': 'Dr. Jane Mutua',
                'notes': 'All items received in good condition'
            },
            format='json'
        )
        self.assertEqual(delivered_response.status_code, 200)
        print(f"✓ DN status: {delivered_response.data['status']}")
        print(f"  - Received by: {delivered_response.data['received_by']}")
        print(f"  - Received at: {delivered_response.data['received_at']}")
        
        # STEP 4: NOW create Invoice referencing the DN
        print("\n=== STEP 4: Create Invoice Referencing DN ===")
        inv_response = self.client.post(
            '/api/invoices/',
            {
                'customer_id': self.customer.id,
                'branch_id': self.branch.id,
                'invoice_date': datetime.now().strftime('%Y-%m-%d'),
                'payment_terms': 'net_30',
                'items': [
                    {
                        'name': 'Medical Supplies Box A',
                        'quantity': 50,
                        'unit_price': Decimal('500.00')
                    },
                    {
                        'name': 'Sterile Gloves',
                        'quantity': 100,
                        'unit_price': Decimal('50.00')
                    }
                ],
                'notes': f'Invoice for delivery note #{dn_number}'
            },
            format='json'
        )
        self.assertEqual(inv_response.status_code, 201)
        inv_data = inv_response.data
        inv_id = inv_data['id']
        inv_number = inv_data['invoice_number']
        print(f"✓ Created Invoice #{inv_number} (ID: {inv_id})")
        print(f"  - Total: {inv_data['total']}")
        
        # STEP 5: Link DN to Invoice
        print("\n=== STEP 5: Link DN to Invoice ===")
        link_response = self.client.post(
            f'/api/delivery-notes/{dn_id}/link-to-invoice/',
            {'invoice_id': inv_id},
            format='json'
        )
        self.assertEqual(link_response.status_code, 200)
        print(f"✓ DN linked to Invoice #{inv_number}")
        print(f"  - DN #{dn_number} now references Invoice #{inv_number}")
        
        # VERIFY: Fetch DN and confirm linking
        print("\n=== VERIFICATION ===")
        final_dn = self.client.get(f'/api/delivery-notes/{dn_id}/').data
        print(f"DN #{dn_number}:")
        print(f"  - Status: {final_dn['status']}")
        print(f"  - Linked Invoice: {final_dn['invoice_number']}")
        print(f"  - Received by: {final_dn['received_by']}")
        
        self.assertEqual(final_dn['invoice_number'], inv_number)
        self.assertEqual(final_dn['status'], 'delivered')
        
        print("\n✓ Pre-Invoice DN Workflow Test PASSED")
```

---

## Deployment Checklist

Before deploying code changes:

- [ ] All tests passing (unit + integration)
- [ ] Code review completed (minimum 2 reviewers)
- [ ] Database migrations tested in staging
- [ ] Performance tests: DN creation with 100+ items
- [ ] API documentation updated
- [ ] Backward compatibility verified (old clients still work)

---

## Rollback Plan

If issues discovered in production:

1. **For P2.1 (Serializer changes):**
   - Revert code changes
   - Restart application servers
   - No database changes = instant rollback

2. **For P2.2 (New endpoint):**
   - Remove route from `urls.py`
   - Restart servers
   - Old clients won't know about endpoint anyway

3. **For P3.1 (Workflow rules):**
   - Disable rule checking temporarily
   - Comment out signal handlers
   - Investigate root cause
   - Re-enable with fixes

---

This completes the implementation guide for all P2 and P3 phases.
