# Delivery Note Enhancement Guide

**Document Date**: March 1, 2026  
**Version**: 1.0  
**Status**: Implementation Ready

---

## Table of Contents

1. [Overview](#overview)
2. [Current State Analysis](#current-state-analysis)
3. [Proposed Enhancements](#proposed-enhancements)
4. [Implementation Plan](#implementation-plan)
5. [Enhanced Serializer](#enhanced-serializer)
6. [API Endpoints](#api-endpoints)
7. [Workflow Integration](#workflow-integration)
8. [Testing Strategy](#testing-strategy)
9. [Deployment Checklist](#deployment-checklist)

---

## Overview

### Goals
1. Enhance delivery note functionality with complete invoice integration
2. Implement line-item fulfillment tracking
3. Create comprehensive workflow state machine
4. Add invoice fulfillment status tracking
5. Improve PDF generation with delivery details

### Target Users
- Sales representatives
- Warehouse staff
- Logistics providers
- Invoice processors
- Finance team

### Success Criteria
- Delivery notes can be tracked against invoices
- Fulfillment status clearly shows which items have been delivered
- Line-item quantities can be partially delivered
- Workflow enforces valid state transitions
- PDF includes all delivery details
- 100% test coverage for delivery note functionality

---

## Current State Analysis

### Existing DeliveryNote Model

**Location**: `finance/invoicing/models.py`

```python
class DeliveryNote(BaseOrder):
    # Identifiers
    delivery_note_number = models.CharField(max_length=100, unique=True, blank=True)
    delivery_date = models.DateField(default=timezone.now)
    
    # Source documents
    source_invoice = models.ForeignKey(Invoice, on_delete=models.SET_NULL, 
                                      null=True, blank=True, 
                                      related_name='dn_from_invoice')
    source_purchase_order = models.ForeignKey('orders.PurchaseOrder',
                                             on_delete=models.SET_NULL,
                                             null=True, blank=True,
                                             related_name='dn_from_po')
    
    # Delivery details
    delivery_address = models.TextField(blank=True)
    driver_name = models.CharField(max_length=100, blank=True)
    driver_phone = models.CharField(max_length=20, blank=True)
    vehicle_number = models.CharField(max_length=50, blank=True)
    
    # Recipient details
    received_by = models.CharField(max_length=100, blank=True)
    received_at = models.DateTimeField(null=True, blank=True)
    receiver_signature = models.ImageField(upload_to='delivery_signatures/', 
                                          null=True, blank=True)
    
    # Special instructions
    special_instructions = models.TextField(blank=True)
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('pending', 'Pending Delivery'),
        ('in_transit', 'In Transit'),
        ('delivered', 'Delivered'),
        ('partially_delivered', 'Partially Delivered'),
        ('cancelled', 'Cancelled'),
    ]
```

### Existing Serializer

**Location**: `finance/invoicing/serializers.py`

```python
class DeliveryNoteSerializer(BaseOrderSerializer):
    class Meta(BaseOrderSerializer.Meta):
        model = DeliveryNote
        fields = BaseOrderSerializer.Meta.fields + [
            'delivery_note_number', 'delivery_date', 'status',
            'source_invoice', 'source_purchase_order',
            'delivery_address', 'driver_name', 'driver_phone',
            'vehicle_number', 'received_by', 'received_at',
            'receiver_signature', 'special_instructions'
        ]

class DeliveryNoteCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeliveryNote
        fields = [...]
```

### Current Gaps

1. **No Fulfillment Tracking**: Cannot track which invoice items have been delivered
2. **No Invoice Status Integration**: Invoice doesn't reflect delivery status
3. **Limited Validation**: No checks for quantity discrepancies
4. **Missing Partial Delivery Logic**: Can't track partial line-item deliveries
5. **Poor PDF Integration**: Delivery note PDFs may not include all details
6. **No Workflow**: State machine not defined for delivery notes

---

## Proposed Enhancements

### 1. Add Fulfillment Model

**Purpose**: Track which invoice items have been delivered

```python
class DeliveryLineItem(models.Model):
    """Track fulfillment of individual invoice items via delivery notes"""
    
    delivery_note = models.ForeignKey('invoicing.DeliveryNote',
                                     on_delete=models.CASCADE,
                                     related_name='fulfilled_items')
    
    # Link to original invoice item
    invoice_item = models.ForeignKey('core_orders.OrderItem',
                                    on_delete=models.PROTECT,
                                    related_name='deliveries')
    
    # Quantities
    invoiced_quantity = models.PositiveIntegerField()  # From invoice
    delivered_quantity = models.PositiveIntegerField()  # Actually delivered
    
    # Tracking
    condition = models.CharField(max_length=50, choices=[
        ('perfect', 'Perfect Condition'),
        ('damaged', 'Damaged'),
        ('defective', 'Defective'),
        ('partial', 'Partial Delivery'),
    ], default='perfect')
    
    notes = models.TextField(blank=True)
    photo = models.ImageField(upload_to='delivery_photos/', null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['delivery_note', 'invoice_item']
        unique_together = [('delivery_note', 'invoice_item')]
    
    def validate_quantity(self):
        """Ensure delivered quantity doesn't exceed invoiced quantity"""
        if self.delivered_quantity > self.invoiced_quantity:
            raise ValidationError(
                f"Delivered quantity ({self.delivered_quantity}) "
                f"cannot exceed invoiced quantity ({self.invoiced_quantity})"
            )
    
    def __str__(self):
        return f"{self.delivery_note.delivery_note_number} - {self.invoice_item.name}"
```

### 2. Add Invoice Fulfillment Status

**Add to Invoice Model**:

```python
class Invoice(BaseOrder):
    # ... existing fields ...
    
    # Fulfillment tracking
    fulfillment_status = models.CharField(max_length=20, choices=[
        ('not_delivered', 'Not Delivered'),
        ('partially_delivered', 'Partially Delivered'),
        ('fully_delivered', 'Fully Delivered'),
    ], default='not_delivered')
    
    fulfilled_at = models.DateTimeField(null=True, blank=True)
    
    def update_fulfillment_status(self):
        """Update fulfillment status based on delivery notes"""
        if not self.items.exists():
            return
        
        total_items = self.items.aggregate(Sum('quantity'))['quantity__sum'] or 0
        if total_items == 0:
            return
        
        # Calculate total delivered
        from finance.invoicing.models import DeliveryLineItem
        delivered_items = DeliveryLineItem.objects.filter(
            invoice_item__order=self
        ).aggregate(Sum('delivered_quantity'))['delivered_quantity__sum'] or 0
        
        # Determine status
        if delivered_items == 0:
            self.fulfillment_status = 'not_delivered'
            self.fulfilled_at = None
        elif delivered_items >= total_items:
            self.fulfillment_status = 'fully_delivered'
            self.fulfilled_at = timezone.now()
        else:
            self.fulfillment_status = 'partially_delivered'
        
        self.save(update_fields=['fulfillment_status', 'fulfilled_at'])
```

### 3. Enhanced Workflow Transitions

**See section: [Workflow Integration](#workflow-integration)**

### 4. Improved Serializers

**See section: [Enhanced Serializer](#enhanced-serializer)**

---

## Implementation Plan

### Phase 1: Database Changes (Week 1)

#### Step 1.1: Create Migration
```bash
python manage.py makemigrations finance

# New fields:
# - Invoice.fulfillment_status
# - Invoice.fulfilled_at
```

#### Step 1.2: Create DeliveryLineItem Model
```bash
python manage.py makemigrations finance
python manage.py migrate
```

### Phase 2: Serializer Updates (Week 1)

#### Step 2.1: Update DeliveryNoteSerializer
- Add fulfillment items serialization
- Add invoice details
- Add quantity tracking

#### Step 2.2: Create DeliveryLineItemSerializer
- Full CRUD operations
- Quantity validation
- Condition tracking

### Phase 3: ViewSet Updates (Week 2)

#### Step 3.1: Update DeliveryNoteViewSet
- Add line item endpoints
- Add fulfillment tracking endpoints
- Add invoice linking

#### Step 3.2: Create DeliveryLineItemViewSet
- CRUD operations
- Validation
- Filtering by delivery note/invoice

### Phase 4: Workflow Implementation (Week 2)

#### Step 4.1: Create delivery_workflows.py
- Define state machine
- Add validation logic
- Add transition handlers

### Phase 5: Testing (Week 2-3)

#### Step 5.1: Unit Tests
- Model tests
- Serializer tests
- Method tests

#### Step 5.2: Integration Tests
- Workflow transitions
- Invoice tracking
- PDF generation

#### Step 5.3: API Tests
- Endpoint tests
- Permission tests
- Error handling

### Phase 6: Documentation & Deployment (Week 3)

#### Step 6.1: Update Documentation
- API docs
- User guides
- Admin guides

#### Step 6.2: Deployment
- Test migrations
- Backup production
- Deploy updates
- Verify functionality

---

## Enhanced Serializer

### DeliveryLineItemSerializer

```python
from rest_framework import serializers
from .models import DeliveryLineItem

class DeliveryLineItemSerializer(serializers.ModelSerializer):
    """Serializer for delivery line items with fulfillment tracking"""
    
    invoice_item_name = serializers.CharField(
        source='invoice_item.name', read_only=True
    )
    invoice_item_sku = serializers.CharField(
        source='invoice_item.sku', read_only=True
    )
    unit_price = serializers.DecimalField(
        source='invoice_item.unit_price', 
        read_only=True, 
        max_digits=15, 
        decimal_places=2
    )
    
    # Quantities
    remaining_quantity = serializers.SerializerMethodField()
    fulfillment_percentage = serializers.SerializerMethodField()
    
    # Status
    is_fully_delivered = serializers.SerializerMethodField()
    is_partial_delivery = serializers.SerializerMethodField()
    
    class Meta:
        model = DeliveryLineItem
        fields = [
            'id',
            'invoice_item',
            'invoice_item_name',
            'invoice_item_sku',
            'invoiced_quantity',
            'delivered_quantity',
            'remaining_quantity',
            'unit_price',
            'total_delivered_value',
            'condition',
            'notes',
            'photo',
            'is_fully_delivered',
            'is_partial_delivery',
            'fulfillment_percentage',
            'created_at',
            'updated_at',
        ]
        read_only_fields = [
            'id',
            'total_delivered_value',
            'remaining_quantity',
            'fulfillment_percentage',
            'is_fully_delivered',
            'is_partial_delivery',
            'created_at',
            'updated_at',
        ]
    
    def get_remaining_quantity(self, obj):
        """Calculate remaining quantity to be delivered"""
        return obj.invoiced_quantity - obj.delivered_quantity
    
    def get_fulfillment_percentage(self, obj):
        """Calculate fulfillment percentage"""
        if obj.invoiced_quantity == 0:
            return 100
        return (obj.delivered_quantity / obj.invoiced_quantity) * 100
    
    def get_is_fully_delivered(self, obj):
        """Check if this line item is fully delivered"""
        return obj.delivered_quantity >= obj.invoiced_quantity
    
    def get_is_partial_delivery(self, obj):
        """Check if this is a partial delivery"""
        return 0 < obj.delivered_quantity < obj.invoiced_quantity
    
    @property
    def total_delivered_value(self):
        """Calculate total value of delivered items"""
        unit_price = self.invoice_item.unit_price
        return self.delivered_quantity * unit_price
    
    def validate(self, data):
        """Validate delivery quantities"""
        if data['delivered_quantity'] > data['invoiced_quantity']:
            raise serializers.ValidationError(
                {
                    'delivered_quantity': (
                        f"Delivered quantity cannot exceed invoiced quantity "
                        f"({data['invoiced_quantity']})"
                    )
                }
            )
        return data


class DeliveryNoteEnhancedSerializer(serializers.ModelSerializer):
    """Enhanced delivery note serializer with fulfillment tracking"""
    
    # Basic information
    delivery_note_number = serializers.CharField(read_only=True)
    order_number = serializers.CharField(read_only=True)
    
    # Customer/Supplier information
    customer_details = ContactSerializer(
        source='customer', 
        read_only=True
    )
    supplier_details = ContactSerializer(
        source='supplier', 
        read_only=True
    )
    
    # Invoice information
    source_invoice_number = serializers.CharField(
        source='source_invoice.invoice_number',
        read_only=True
    )
    source_invoice_details = InvoiceFrontendSerializer(
        source='source_invoice',
        read_only=True
    )
    
    # Line items with fulfillment
    fulfilled_items = DeliveryLineItemSerializer(
        many=True,
        read_only=True,
        source='delivery_note.fulfilled_items'
    )
    items = OrderItemSerializer(
        many=True,
        read_only=True
    )
    
    # Fulfillment summary
    fulfillment_summary = serializers.SerializerMethodField()
    total_delivered_value = serializers.SerializerMethodField()
    fulfillment_percentage = serializers.SerializerMethodField()
    
    # Status tracking
    is_fully_delivered = serializers.SerializerMethodField()
    is_partially_delivered = serializers.SerializerMethodField()
    
    # Delivery details
    delivery_address = serializers.CharField()
    driver_name = serializers.CharField()
    driver_phone = serializers.CharField()
    vehicle_number = serializers.CharField()
    received_by = serializers.CharField()
    received_at = serializers.DateTimeField()
    receiver_signature = serializers.ImageField()
    special_instructions = serializers.CharField()
    
    # Timestamps
    status_display = serializers.CharField(
        source='get_status_display',
        read_only=True
    )
    
    class Meta:
        model = DeliveryNote
        fields = [
            # Identifiers
            'id',
            'delivery_note_number',
            'order_number',
            'delivery_date',
            'status',
            'status_display',
            
            # Source documents
            'source_invoice',
            'source_invoice_number',
            'source_invoice_details',
            'source_purchase_order',
            
            # Parties
            'customer_details',
            'supplier_details',
            
            # Line items
            'items',
            'fulfilled_items',
            'fulfillment_summary',
            
            # Fulfillment tracking
            'total_delivered_value',
            'fulfillment_percentage',
            'is_fully_delivered',
            'is_partially_delivered',
            
            # Delivery details
            'delivery_address',
            'driver_name',
            'driver_phone',
            'vehicle_number',
            'received_by',
            'received_at',
            'receiver_signature',
            'special_instructions',
            
            # Financial summary
            'subtotal',
            'tax_amount',
            'discount_amount',
            'shipping_cost',
            'total',
            
            # Metadata
            'created_at',
            'updated_at',
            'created_by',
        ]
        read_only_fields = [
            'id',
            'delivery_note_number',
            'order_number',
            'fulfilled_items',
            'fulfillment_summary',
            'total_delivered_value',
            'fulfillment_percentage',
            'is_fully_delivered',
            'is_partially_delivered',
            'source_invoice_number',
            'source_invoice_details',
            'customer_details',
            'supplier_details',
            'created_at',
            'updated_at',
            'created_by',
            'status_display',
        ]
    
    def get_fulfillment_summary(self, obj):
        """Get fulfillment summary with counts"""
        from django.db.models import Count, Q
        from finance.invoicing.models import DeliveryLineItem
        
        fulfilled = DeliveryLineItem.objects.filter(
            delivery_note__source_invoice=obj.source_invoice
        ).aggregate(
            fully_delivered=Count('id', filter=Q(
                delivered_quantity__gte=F('invoiced_quantity')
            )),
            partially_delivered=Count('id', filter=Q(
                delivered_quantity__gt=0,
                delivered_quantity__lt=F('invoiced_quantity')
            )),
            not_delivered=Count('id', filter=Q(delivered_quantity=0))
        )
        
        return fulfilled
    
    def get_total_delivered_value(self, obj):
        """Calculate total value of delivered items"""
        from finance.invoicing.models import DeliveryLineItem
        
        items = DeliveryLineItem.objects.filter(
            delivery_note=obj
        ).aggregate(
            total=Sum(F('delivered_quantity') * F('invoice_item__unit_price'))
        )
        
        return items['total'] or Decimal('0.00')
    
    def get_fulfillment_percentage(self, obj):
        """Calculate overall fulfillment percentage"""
        from finance.invoicing.models import DeliveryLineItem
        
        total_invoiced = obj.items.aggregate(
            Sum('quantity')
        )['quantity__sum'] or 0
        
        if total_invoiced == 0:
            return 100
        
        total_delivered = DeliveryLineItem.objects.filter(
            delivery_note=obj
        ).aggregate(Sum('delivered_quantity'))['delivered_quantity__sum'] or 0
        
        return (total_delivered / total_invoiced) * 100
    
    def get_is_fully_delivered(self, obj):
        """Check if all items are delivered"""
        return self.get_fulfillment_percentage(obj) >= 100
    
    def get_is_partially_delivered(self, obj):
        """Check if some items are delivered"""
        percentage = self.get_fulfillment_percentage(obj)
        return 0 < percentage < 100
```

---

## API Endpoints

### Delivery Note Endpoints

#### List Delivery Notes
```
GET /api/delivery-notes/
Query Parameters:
  - status: draft, pending, in_transit, delivered, etc.
  - source_invoice: Filter by source invoice
  - delivery_date_from, delivery_date_to: Date range
  - search: Search by delivery_note_number
  - ordering: Sort field (-delivery_date, delivery_note_number, etc.)
  - page: Pagination
```

#### Create Delivery Note
```
POST /api/delivery-notes/
{
    "source_invoice": 123,
    "delivery_address": "123 Main St, City",
    "driver_name": "John Doe",
    "driver_phone": "+254123456789",
    "vehicle_number": "ABC-123",
    "special_instructions": "Handle with care"
}
```

#### Get Delivery Note Details
```
GET /api/delivery-notes/{id}/
```

#### Update Delivery Note
```
PATCH /api/delivery-notes/{id}/
{
    "status": "in_transit",
    "driver_name": "New Driver"
}
```

#### Mark as Delivered
```
POST /api/delivery-notes/{id}/mark-delivered/
{
    "received_by": "Customer Name",
    "notes": "Received in perfect condition"
}
```

#### Generate PDF
```
GET /api/delivery-notes/{id}/pdf/
```

### DeliveryLineItem Endpoints

#### List Fulfilled Items
```
GET /api/delivery-notes/{delivery_note_id}/fulfilled-items/
```

#### Add Fulfilled Item
```
POST /api/delivery-notes/{delivery_note_id}/fulfilled-items/
{
    "invoice_item": 456,
    "delivered_quantity": 5,
    "condition": "perfect",
    "notes": "Delivered without damage"
}
```

#### Update Fulfilled Item
```
PATCH /api/delivery-notes/{delivery_note_id}/fulfilled-items/{item_id}/
{
    "delivered_quantity": 4,
    "condition": "damaged",
    "notes": "One unit arrived damaged"
}
```

#### Get Fulfillment Summary
```
GET /api/invoices/{invoice_id}/fulfillment-summary/
Returns:
{
    "fulfillment_status": "partially_delivered",
    "items_not_delivered": 3,
    "items_partially_delivered": 2,
    "items_fully_delivered": 5,
    "total_fulfilled_value": 5000.00,
    "fulfillment_percentage": 75.5,
    "delivery_notes": [...]
}
```

---

## Workflow Integration

**See File**: [04_WORKFLOW_IMPLEMENTATION.md](04_WORKFLOW_IMPLEMENTATION.md)

Key workflow transitions for delivery notes:
- Draft → Pending Delivery
- Pending Delivery → In Transit
- In Transit → Delivered (or Partially Delivered)
- Any status → Cancelled

---

## Testing Strategy

**See File**: [05_TESTING_GUIDE.md](05_TESTING_GUIDE.md)

### Unit Tests Required
- [ ] DeliveryLineItem model validation
- [ ] Invoice fulfillment status calculation
- [ ] Quantity tracking logic
- [ ] Serializer validation

### Integration Tests Required
- [ ] Create delivery note from invoice
- [ ] Track line item fulfillment
- [ ] Update invoice fulfillment status
- [ ] Partial delivery scenarios

### API Tests Required
- [ ] Create delivery note endpoint
- [ ] Add fulfilled items endpoint
- [ ] Mark delivered endpoint
- [ ] Permission checks
- [ ] Error scenarios

---

## Deployment Checklist

- [ ] Code review completed
- [ ] All tests passing (100% coverage)
- [ ] Database migrations tested
- [ ] PDF generation tested with new fields
- [ ] API documentation updated
- [ ] User documentation created
- [ ] Admin interface configured
- [ ] Backup created before deployment
- [ ] Deployment to staging
- [ ] Staging validation
- [ ] Deployment to production
- [ ] Production validation
- [ ] User training completed
- [ ] Support documentation provided

---

## Rollback Plan

### In Case of Issues
1. Stop the deployment
2. Revert database migrations: `python manage.py migrate finance <previous_migration>`
3. Redeploy previous version
4. Notify users of delay
5. Schedule post-mortem analysis

### Data Safety
- All migrations are reversible
- Backup created before deployment
- Test migrations on staging first

---

**Document Version**: 1.0  
**Status**: Ready for Implementation  
**Estimated Effort**: 40-60 hours  
**Timeline**: 2-3 weeks
