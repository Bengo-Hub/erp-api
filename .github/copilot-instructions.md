# Copilot Instructions for Bengobox ERP API

**Project:** Django REST Framework ERP system  
**Stack:** Django 5.0, DRF, PostgreSQL, Celery, Redis, Docker  
**Key Pattern:** Modular apps with standardized response/audit/error handling

---

## 🏗️ Architecture Overview

### System Components
- **Frontend:** Vue.js 3 + Vite (separate repo: bengobox-erp-ui)
- **Backend:** Django + DRF API
- **Jobs:** Celery + Redis (background tasks, periodic jobs)
- **Real-time:** Django Channels (WebSockets)
- **Database:** PostgreSQL
- **Cache:** Redis
- **Project Config:** `ProcureProKEAPI/settings.py`, `ProcureProKEAPI/urls.py`

### Modular App Structure
```
Finance/                          # Business domain module
├── invoicing/                    # Sub-feature with own models/serializers/views
│   ├── models.py                 # Domain models (Invoice, DeliveryNote, etc.)
│   ├── serializers.py            # DRF serializers for API endpoints
│   ├── views.py                  # ViewSet + custom actions
│   ├── filters.py                # QuerySet filters for list endpoints
│   ├── signals.py                # Django signals (post_save, pre_delete)
│   ├── pdf_generator.py          # Domain-specific utilities
│   ├── tests.py                  # Unit + integration tests
│   └── urls.py                   # URL routing for this feature
├── accounts/                     # Chart of accounts (GL)
├── payment/                      # Payment processing
└── ...
```

**Key Principle:** Each business domain (finance, inventory, HR, CRM) is a Django app. Each feature within a domain (invoicing, budgets, reconciliation) is a subfolder with complete isolation.

---

## 📋 Critical Patterns & Conventions

### 1. API Response Wrapper (MANDATORY)
**Location:** `core/response.py` → `APIResponse` class

**Usage:**
```python
from core.response import APIResponse

# Success response
return APIResponse.success(
    data=serializer.data,
    message='Invoice created successfully',
    status_code=status.HTTP_201_CREATED
)

# Error response
return APIResponse.error(
    error_code='INVOICE_001',
    message='Invalid customer ID',
    status_code=status.HTTP_400_BAD_REQUEST,
    details={'customer_id': 'Customer not found'}
)
```
**Why:** Ensures consistent response format for frontend: `{success, message, data, timestamp, correlation_id}`

---

### 2. Base ViewSet & Error Handling (MANDATORY)
**Location:** `core/base_viewsets.py` → `BaseModelViewSet`

**Usage:**
```python
from core.base_viewsets import BaseModelViewSet

class InvoiceViewSet(BaseModelViewSet):
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    permission_classes = [IsAuthenticated]
    filterset_class = InvoiceFilter
    
    def perform_create(self, serializer):
        # Automatically wraps APIResponse + audit logging
        instance = serializer.save(created_by=self.request.user)
        self.log_operation('CREATE', instance)
        return instance
```
**Why:** All CRUD responses automatically wrapped in APIResponse, with audit logging and correlation tracking.

---

### 3. Audit Trail Logging (MANDATORY for data changes)
**Location:** `core/audit.py` → `AuditTrail` class

**Usage:**
```python
from core.audit import AuditTrail

# Log create/update/delete operations
AuditTrail.log(
    operation='UPDATE',
    module='finance',
    entity_type='Invoice',
    entity_id=invoice.id,
    user=request.user,
    changes={'status': ('draft', 'sent')},
    reason='Invoice status changed to sent'
)
```
**Why:** Compliance + debugging. Every business operation is traceable.

---

### 4. Money Field Handling (NON-NEGOTIABLE)
**Location:** `core/MONEY_FIELD_GUIDE.md` + `core/serializer_fields.py`

**Usage:**
```python
from core.serializer_fields import MoneyField
from django_money.models.fields import MoneyField as DjangoMoneyField

# In models.py
total = DjangoMoneyField(max_digits=14, decimal_places=2, default_currency='KES')

# In serializers.py
total = MoneyField(required=False)  # Handles currency conversion automatically
```
**Why:** Multi-currency ERP. Incorrect money handling = financial loss. See `core/MONEY_FIELD_GUIDE.md` for complete patterns.

---

### 5. Transaction Atomicity for Complex Operations
**Location:** Standard Django pattern

**Usage:**
```python
from django.db import transaction

@transaction.atomic
def link_delivery_note_to_invoice(delivery_note_id, invoice_id):
    """All-or-nothing: if validation fails, no data changes"""
    delivery_note = DeliveryNote.objects.get(id=delivery_note_id)
    invoice = Invoice.objects.get(id=invoice_id)
    
    # Validations
    if delivery_note.customer_id != invoice.customer_id:
        raise ValidationError('Customer mismatch')
    
    # Linking
    delivery_note.invoice = invoice
    delivery_note.save()
    
    # Audit
    AuditTrail.log(operation='LINK', ...)
```
**Why:** Multi-step operations must be atomic. Post-save signals run inside transaction.

---

### 6. Model Design Pattern
**Location:** `core/models.py` → `BaseModel` + domain models

**Key Fields (inherited from BaseModel):**
- `id` (UUID)
- `created_at`, `updated_at` (auto-set)
- `created_by`, `updated_by` (FK to User)
- `is_active` (soft delete)

**Domain-Specific:** Each model has business fields + relationships
```python
class Invoice(BaseOrder):  # Extends BaseOrder for line items
    customer = models.ForeignKey(Contact, ...)  # Who it's for
    branch = models.ForeignKey(Branch, ...)     # Which location
    status = models.CharField(choices=[...])    # State machine
    total = DjangoMoneyField(...)               # ALWAYS use MoneyField
    
    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['customer', 'status'])]
```

---

### 7. Serializer Patterns
**Location:** `finance/invoicing/serializers.py`

**Nested Creation (Invoice with Items):**
```python
class OrderItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = OrderItem
        fields = ['id', 'product_id', 'quantity', 'unit_price', 'subtotal']

class InvoiceSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, source='items_set', required=False)
    
    class Meta:
        model = Invoice
        fields = ['id', 'customer', 'branch', 'items', 'total', 'status']
    
    def create(self, validated_data):
        items_data = validated_data.pop('items_set', [])
        invoice = Invoice.objects.create(**validated_data)
        
        for item in items_data:
            OrderItem.objects.create(order=invoice, **item)
        
        return invoice
```
**Why:** Frontend sends nested data; serializers handle atomicity.

---

### 8. Custom ViewSet Actions
**Location:** `finance/invoicing/views.py`

**Pattern for Complex Operations:**
```python
from rest_framework.decorators import action

class InvoiceViewSet(BaseModelViewSet):
    @action(
        detail=True,
        methods=['post'],
        permission_classes=[IsAuthenticated],
        url_path='record-payment'
    )
    def record_payment(self, request, pk=None):
        """Convert POST /invoices/{id}/record-payment/ into business operation"""
        invoice = self.get_object()
        amount = request.data.get('amount')
        
        # Validation + business logic
        if amount > invoice.balance_due:
            return APIResponse.error(
                error_code='PAYMENT_001',
                message='Payment exceeds balance'
            )
        
        # Execute atomically
        with transaction.atomic():
            payment = Payment.objects.create(
                invoice=invoice,
                amount=amount,
                created_by=request.user
            )
            invoice.record_payment(amount)
            self.log_operation('RECORD_PAYMENT', invoice, changes={'balance_due': ...})
        
        return APIResponse.success(
            data=InvoiceSerializer(invoice).data,
            message='Payment recorded'
        )
```
**Why:** Complex operations belong in views as @action methods, not separate endpoints.

---

### 9. Celery Task Pattern
**Location:** `finance/invoicing/tasks.py`

**Pattern:**
```python
from celery import shared_task
from core.audit import AuditTrail

@shared_task
def send_invoice_email(invoice_id, recipient_email):
    """Async task - failures don't block API response"""
    try:
        invoice = Invoice.objects.get(id=invoice_id)
        email_body = generate_html_email(invoice)
        send_email(
            to=recipient_email,
            subject=f'Invoice {invoice.invoice_number}',
            html_message=email_body
        )
        AuditTrail.log(operation='EMAIL_SENT', ...)
    except Exception as e:
        logger.error(f'Failed to send invoice email: {e}')
        # Don't raise - Celery will keep retrying
```
**Trigger in model signal:**
```python
from django.db.models.signals import post_save

@receiver(post_save, sender=Invoice)
def invoice_sent(sender, instance, created, **kwargs):
    if instance.status == 'sent':
        send_invoice_email.delay(instance.id, instance.customer.email)
```
**Why:** Email/PDF generation shouldn't block API. Use `.delay()` for async.

---

### 10. Model Signals (Use Sparingly)
**Location:** `finance/invoicing/signals.py`

**When to use:**
- Auto-update denormalized fields (update cache, summary totals)
- Trigger async tasks (email, document generation)
- Create related records (audit trail)

**Pattern:**
```python
@receiver(post_save, sender=Invoice)
def update_business_totals(sender, instance, created, **kwargs):
    """Update cached totals on Invoice change"""
    business = instance.branch.business
    business.total_invoiced = Invoice.objects.filter(
        branch__business=business
    ).aggregate(total=Sum('total'))['total']
    business.save(update_fields=['total_invoiced'])
```
**Avoid:** Complex business logic in signals → hard to test, non-obvious flow. Put in models/services instead.

---

## 🧪 Testing Patterns

**Location:** `finance/invoicing/tests.py` → `APITestCase`

**Pattern:**
```python
from rest_framework.test import APITestCase, APIClient
from django.utils import timezone

class InvoiceTests(APITestCase):
    def setUp(self):
        """Run before each test"""
        self.client = APIClient()
        self.user = User.objects.create_user(username='test', password='pass')
        self.client.force_authenticate(user=self.user)
        
        # Create minimal fixtures
        self.business = Bussiness.objects.create(owner=self.user, name='TestCo')
        self.contact = Contact.objects.create(user=self.user, business=self.business)
    
    def test_create_invoice_with_items(self):
        """Test happy path + validations"""
        url = '/api/v1/finance/invoicing/invoices/'
        payload = {
            'customer': self.contact.id,
            'branch': self.branch.id,
            'total': 2500,
            'items': [{
                'product_id': self.product.id,
                'quantity': 1,
                'unit_price': 2500
            }]
        }
        
        response = self.client.post(url, payload, format='json')
        
        # Assert response structure (APIResponse wrapper)
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()['success'])
        self.assertIn('data', response.json())
        
        # Assert database state
        self.assertTrue(Invoice.objects.filter(customer=self.contact).exists())
        self.assertEqual(OrderItem.objects.count(), 1)
```

---

## 🔄 Workflow Guidelines

### Creating a New Feature
1. **Add model** in `module/feature/models.py` (inherit from `BaseModel`)
2. **Add serializer** in `module/feature/serializers.py` (use `APIResponse` pattern)
3. **Add viewset** in `module/feature/views.py` (inherit from `BaseModelViewSet`)
4. **Add URL routing** in `module/feature/urls.py`
5. **Add tests** in `module/feature/tests.py` (APITestCase pattern)
6. Register app in `ProcureProKEAPI/settings.py` INSTALLED_APPS if new module

### Modifying Existing Feature
1. Check `models.py` for state machine/validations
2. Check `serializers.py` for API contract
3. Check `tests.py` to understand expected behavior
4. Update in this order: tests → code → commit
5. Update audit trail calls if data changes

---

## 📦 Key Dependencies & Locations

| Concern | Location | Pattern |
|---------|----------|---------|
| API responses | `core/response.py` | `APIResponse.success/error()` |
| ViewSet base | `core/base_viewsets.py` | `BaseModelViewSet` |
| Audit trail | `core/audit.py` | `AuditTrail.log()` |
| Money fields | `core/serializer_fields.py` | `MoneyField` + `DjangoMoneyField` |
| Model base | `core/models.py` | `BaseModel` |
| Auth | `authmanagement/` | JWT + SimpleJWT |
| Async tasks | `ProcureProKEAPI/celery.py` | `@shared_task`, `.delay()` |
| Admin UI | `jazzmin` + `core/admin.py` | Auto-generated from models |

---

## 🚫 Common Pitfalls & Anti-Patterns

1. **Don't create custom Response classes.** Use `APIResponse` from `core/response.py`
2. **Don't call `.save()` directly in ViewSets.** Use `serializer.save()` with overrides.
3. **Don't put business logic in signals.** Use model methods or service objects.
4. **Don't forget audit logging** on CREATE/UPDATE/DELETE operations.
5. **Don't use string amounts.** Always use `MoneyField` for financial values.
6. **Don't make API calls inside model methods.** Use tasks or services.
7. **Don't skip transaction.atomic()** for multi-step operations.
8. **Don't ignore correlation IDs.** They're auto-tracked in BaseViewSet.

---

## 🔗 Documentation Cross-References

- **Architecture:** See `docs/INDEX.md` for system overview
- **Money Fields:** See `core/MONEY_FIELD_GUIDE.md` for currency handling
- **Invoice Workflows:** See `docs/tests/finance/invoice/` for complete feature design
- **API Docs:** Automatically generated at `/api/schema/swagger/` (drf-spectacular)

---

## 💡 Pro Tips

- **Correlation IDs:** Auto-generated in requests, use `get_correlation_id()` in services for tracing
- **Feature Flags:** Check `ProcureProKEAPI/settings.py` for feature toggles (e.g., `ENABLE_INVOICE_WORKFLOWS`)
- **Test Fixtures:** Reuse in `setUp()` across test classes; create specific ones in each test
- **Celery Tasks:** Always add `.delay()` for async, not `.apply_async()` unless you need advanced options
- **Soft Deletes:** Models have `is_active` field; use `.filter(is_active=True)` if needed

---

**Last Updated:** 2026-02-26 | For questions, refer to source files or docs/
