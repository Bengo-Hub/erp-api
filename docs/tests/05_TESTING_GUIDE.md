# Testing Guide & Test Coverage

**Document Date**: March 1, 2026  
**Version**: 1.0  
**Status**: Implementation Ready

---

## Table of Contents

1. [Testing Strategy](#testing-strategy)
2. [Current Coverage Analysis](#current-coverage-analysis)
3. [Test Structure](#test-structure)
4. [Unit Tests](#unit-tests)
5. [Integration Tests](#integration-tests)
6. [API Tests](#api-tests)
7. [Test Fixtures and Factories](#test-fixtures-and-factories)
8. [Running Tests](#running-tests)
9. [Coverage Goals](#coverage-goals)

---

## Testing Strategy

### Testing Pyramid

```
           /\
          /E2E\       (End-to-End Tests - 10%)
         /------\
        / Integration\ (Integration Tests - 30%)
       /----------\
      /    Unit    \  (Unit Tests - 60%)
     /____________\
```

### Testing Levels

#### Level 1: Unit Tests (60%)
- Test individual functions/methods
- Test model methods
- Test serializer validation
- Fast execution
- No database setup (use mocks)

#### Level 2: Integration Tests (30%)
- Test model relationships
- Test workflow transitions
- Test service interactions
- Database required
- Slower execution

#### Level 3: API Tests (10%)
- Test endpoint functionality
- Test authentication/permissions
- Test response formats
- Test error handling
- Real API calls through Django test client

---

## Current Coverage Analysis

### Overall Status
```
Current Coverage: ~30%
Target Coverage: 80%+ by Phase 2

By Module:
┌─────────────────┬──────┬───────┬──────────┐
│ Module          │ %    │ Tests │ Priority │
├─────────────────┼──────┼───────┼──────────┤
│ authmanagement  │ 70%  │ 45    │ LOW      │
│ core            │ 50%  │ 35    │ MEDIUM   │
│ finance         │ 40%  │ 25    │ HIGH     │
│ procurement     │ 25%  │ 15    │ HIGH     │
│ hrm             │ 20%  │ 12    │ MEDIUM   │
│ business        │ 15%  │ 8     │ LOW      │
│ crm             │ 15%  │ 8     │ MEDIUM   │
│ notifications   │ 25%  │ 15    │ MEDIUM   │
└─────────────────┴──────┴───────┴──────────┘
```

### Gaps by Module

**Finance (40%)**
- Missing: Invoice calculations, payment tracking, PDF generation
- Missing: DeliveryNote fulfillment tracking
- Missing: CreditNote/DebitNote operations
- Missing: Payment workflow integration

**Procurement (25%)**
- Missing: Order approval workflow
- Missing: Supplier validation
- Missing: Budget checks
- Missing: PO to DeliveryNote link

**HRM (20%)**
- Missing: Payroll calculations (edge cases)
- Missing: Leave balance calculations
- Missing: Attendance reports
- Missing: Recruitment workflow

---

## Test Structure

### Directory Layout

```
tests/
├── __init__.py
├── conftest.py                    # Pytest configuration
├── factories.py                   # Model factories
├── fixtures.py                    # Test fixtures
├── test_*.py                      # Test modules organized by app
│
├── finance/
│   ├── test_invoice_models.py
│   ├── test_invoice_serializers.py
│   ├── test_invoice_views.py
│   ├── test_delivery_note_models.py
│   ├── test_delivery_note_serializers.py
│   ├── test_delivery_note_views.py
│   ├── test_delivery_workflow.py
│   └── test_payment_models.py
│
├── procurement/
│   ├── test_purchase_order_models.py
│   ├── test_purchase_order_views.py
│   └── test_procurement_workflow.py
│
├── core/
│   ├── test_base_viewsets.py
│   ├── test_serializers.py
│   ├── test_utils.py
│   └── test_workflows.py
│
├── hrm/
│   ├── test_employee_models.py
│   └── test_payroll_calculations.py
│
└── documentation/
    ├── INDEX.md
    ├── 01_CODEBASE_AUDIT.md
    └── ... (other docs)
```

---

## Unit Tests

### Finance Module - Invoice Tests

```python
# tests/finance/test_invoice_models.py

import pytest
from django.utils import timezone
from django.core.exceptions import ValidationError
from decimal import Decimal
from finance.invoicing.models import Invoice, InvoicePayment
from tests.factories import InvoiceFactory, ContactFactory

@pytest.mark.django_db
class TestInvoiceModel:
    """Unit tests for Invoice model"""
    
    def test_invoice_creation(self):
        """Test basic invoice creation"""
        invoice = InvoiceFactory()
        assert invoice.id is not None
        assert invoice.status == 'draft'
        assert invoice.amount_paid == Decimal('0.00')
    
    def test_generate_invoice_number(self):
        """Test auto-generation of invoice number"""
        invoice = InvoiceFactory(invoice_number='')
        invoice.save()
        assert invoice.invoice_number is not None
        assert invoice.invoice_number.startswith('INV')
    
    def test_balance_due_calculation(self):
        """Test balance due is calculated correctly"""
        invoice = InvoiceFactory(
            subtotal=Decimal('1000.00'),
            tax_amount=Decimal('100.00'),
            discount_amount=Decimal('0.00'),
            shipping_cost=Decimal('0.00')
        )
        assert invoice.balance_due == Decimal('1100.00')
    
    def test_balance_due_after_payment(self):
        """Test balance due after recording payment"""
        invoice = InvoiceFactory(total=Decimal('1000.00'))
        
        # Record payment
        payment = invoice.record_payment(
            amount=Decimal('500.00'),
            payment_date=timezone.now().date(),
            payment_account_id=1,
            user=None
        )
        
        # Refresh from database
        invoice.refresh_from_db()
        
        assert invoice.amount_paid == Decimal('500.00')
        assert invoice.balance_due == Decimal('500.00')
        assert invoice.status == 'partially_paid'
    
    def test_void_invoice(self):
        """Test voiding an invoice"""
        invoice = InvoiceFactory(status='sent')
        invoice.void_invoice(reason="Duplicate invoice issued")
        
        invoice.refresh_from_db()
        assert invoice.status == 'void'
        assert 'Duplicate' in invoice.notes
    
    def test_recalculate_payments_syncs_amount(self):
        """Test recalculate_payments syncs with payment records"""
        invoice = InvoiceFactory(total=Decimal('1000.00'))
        
        # Directly create payment records (simulating multiple payments)
        InvoicePaymentFactory(invoice=invoice, amount=Decimal('300.00'))
        InvoicePaymentFactory(invoice=invoice, amount=Decimal('200.00'))
        
        # Sync
        invoice.recalculate_payments()
        invoice.refresh_from_db()
        
        assert invoice.amount_paid == Decimal('500.00')
        assert invoice.balance_due == Decimal('500.00')
```

### Delivery Note Tests

```python
# tests/finance/test_delivery_note_models.py

@pytest.mark.django_db
class TestDeliveryNoteModel:
    """Unit tests for DeliveryNote model"""
    
    def test_delivery_note_from_invoice(self):
        """Test creating delivery note from invoice"""
        invoice = InvoiceFactory()
        
        delivery_note = DeliveryNote.create_from_invoice(
            invoice=invoice,
            delivery_address="123 Main St"
        )
        
        assert delivery_note.source_invoice == invoice
        assert delivery_note.customer == invoice.customer
        assert delivery_note.delivery_address == "123 Main St"
        assert delivery_note.total == invoice.total
    
    def test_mark_delivered(self):
        """Test marking delivery note as delivered"""
        delivery_note = DeliveryNoteFactory(status='in_transit')
        
        delivery_note.mark_delivered(
            received_by="John Doe",
            notes="Received in good condition"
        )
        
        delivery_note.refresh_from_db()
        assert delivery_note.status == 'delivered'
        assert delivery_note.received_by == "John Doe"
        assert delivery_note.received_at is not None
```

---

## Integration Tests

### Delivery Note Workflow Integration

```python
# tests/finance/test_delivery_workflow.py

@pytest.mark.django_db
class TestDeliveryNoteWorkflow:
    """Integration tests for delivery note workflow"""
    
    def test_full_delivery_workflow(self):
        """Test complete delivery workflow"""
        # Setup
        invoice = InvoiceFactory()
        delivery_note = DeliveryNote.create_from_invoice(invoice)
        
        # Step 1: Confirm
        delivery_note.delivery_address = "123St"
        delivery_note.delivery_date = timezone.now().date()
        workflow = DeliveryNoteWorkflow(delivery_note)
        workflow.execute_transition('confirmed')
        
        delivery_note.refresh_from_db()
        assert delivery_note.status == 'confirmed'
        
        # Step 2: Ready for pickup
        workflow.execute_transition('ready_for_pickup')
        delivery_note.refresh_from_db()
        assert delivery_note.status == 'ready_for_pickup'
        
        # Step 3: In transit
        delivery_note.driver_name = "John"
        delivery_note.vehicle_number = "ABC-123"
        delivery_note.save()
        workflow.execute_transition('in_transit')
        
        delivery_note.refresh_from_db()
        assert delivery_note.status == 'in_transit'
        
        # Step 4: Delivered
        delivery_note.received_by = "Customer"
        delivery_note.save()
        workflow.execute_transition('delivered')
        
        delivery_note.refresh_from_db()
        assert delivery_note.status == 'delivered'
        assert delivery_note.received_at is not None
        
        # Verify invoice fulfillment updated
        invoice.refresh_from_db()
        assert invoice.fulfillment_status == 'fully_delivered'
    
    def test_partial_delivery_workflow(self):
        """Test partial delivery workflow"""
        invoice = InvoiceFactory(items_count=5)
        delivery_note = DeliveryNote.create_from_invoice(invoice)
        
        # Deliver only 3 items
        items = invoice.items.all()[:3]
        for item in items:
            DeliveryLineItem.objects.create(
                delivery_note=delivery_note,
                invoice_item=item,
                invoiced_quantity=item.quantity,
                delivered_quantity=item.quantity
            )
        
        # Status should reflect partial delivery
        workflow = DeliveryNoteWorkflow(delivery_note)
        workflow.execute_transition('partial_delivery')
        
        invoice.update_fulfillment_status()
        invoice.refresh_from_db()
        
        assert invoice.fulfillment_status == 'partially_delivered'
```

---

## API Tests

### Invoice Endpoint Tests

```python
# tests/finance/test_invoice_views.py

@pytest.mark.django_db
class TestInvoiceViewSet:
    """API tests for invoice endpoints"""
    
    def test_create_invoice(self, authenticated_client):
        """Test POST /api/invoices/"""
        payload = {
            'customer': 123,
            'invoice_date': '2026-03-01',
            'payment_terms': 'net_30',
            'items': [
                {
                    'product_id': 456,
                    'quantity': 5,
                    'unit_price': '100.00'
                }
            ]
        }
        
        response = authenticated_client.post('/api/invoices/', payload, format='json')
        
        assert response.status_code == 201
        assert 'invoice_number' in response.data
    
    def test_list_invoices_filtered_by_status(self, authenticated_client):
        """Test GET /api/invoices/?status=draft"""
        InvoiceFactory.create_batch(5, status='draft')
        InvoiceFactory.create_batch(3, status='paid')
        
        response = authenticated_client.get('/api/invoices/?status=draft')
        
        assert response.status_code == 200
        assert len(response.data['results']) == 5
    
    def test_record_payment(self, authenticated_client):
        """Test POST /api/invoices/{id}/record-payment/"""
        invoice = InvoiceFactory(total=Decimal('1000.00'))
        
        payload = {
            'amount': '500.00',
            'payment_date': '2026-03-01',
            'payment_account': 1
        }
        
        response = authenticated_client.post(
            f'/api/invoices/{invoice.id}/record-payment/',
            payload,
            format='json'
        )
        
        assert response.status_code == 200
        
        invoice.refresh_from_db()
        assert invoice.amount_paid == Decimal('500.00')
```

---

## Test Fixtures and Factories

### Using Factory Boy

```python
# tests/factories.py

import factory
from faker import Faker
from django.utils import timezone
from decimal import Decimal
from finance.invoicing.models import Invoice, DeliveryNote
from procurement.orders.models import PurchaseOrder
from crm.contacts.models import Contact
from business.models import Bussiness, Branch

fake = Faker()

class ContactFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Contact
    
    first_name = factory.Faker('first_name')
    last_name = factory.Faker('last_name')
    email = factory.Faker('email')
    phone = factory.Faker('phone_number')
    business_name = factory.Faker('company')
    contact_type = 'customer'

class BranchFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Branch
    
    name = factory.Faker('city')
    business = factory.SubFactory('tests.factories.BusinessFactory')

class BusinessFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Bussiness
    
    name = factory.Faker('company')
    registration_number = factory.Faker('bothify')
    email = factory.Faker('email')

class InvoiceFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = Invoice
    
    customer = factory.SubFactory(ContactFactory)
    branch = factory.SubFactory(BranchFactory)
    invoice_date = factory.LazyFunction(lambda: timezone.now().date())
    due_date = factory.LazyFunction(lambda: (timezone.now() + timezone.timedelta(days=30)).date())
    subtotal = Decimal('1000.00')
    tax_amount = Decimal('100.00')
    total = Decimal('1100.00')
    status = 'draft'
    
    @factory.post_generation
    def items(obj, create, extracted, **kwargs):
        """Add line items"""
        if not create:
            return
        
        if extracted:
            for item in extracted:
                obj.items.add(item)
        else:
            # Create default item
            from tests.factories import OrderItemFactory
            OrderItemFactory(order=obj)

class DeliveryNoteFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = DeliveryNote
    
    source_invoice = factory.SubFactory(InvoiceFactory)
    delivery_date = factory.LazyFunction(lambda: timezone.now().date())
    status = 'draft'
    delivery_address = factory.Faker('address')
    driver_name = factory.Faker('name')
    vehicle_number = factory.Faker('license_plate')

class InvoicePaymentFactory(factory.django.DjangoModelFactory):
    class Meta:
        model = InvoicePayment
    
    invoice = factory.SubFactory(InvoiceFactory)
    amount = Decimal('100.00')
    payment_date = factory.LazyFunction(lambda: timezone.now().date())
```

---

## Running Tests

### Setup

```bash
# Install test dependencies
pip install pytest pytest-django pytest-cov factory-boy faker

# Create pytest.ini
[pytest]
DJANGO_SETTINGS_MODULE = ProcureProKEAPI.settings
python_files = tests.py test_*.py *_tests.py

# Create conftest.py
import os
import django
from django.conf import settings

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ProcureProKEAPI.settings')
django.setup()
```

### Run All Tests

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=. --cov-report=html

# Run specific module
pytest tests/finance/

# Run specific test
pytest tests/finance/test_invoice_models.py::TestInvoiceModel::test_invoice_creation

# Run with verbose output
pytest -v

# Run tests matching pattern
pytest -k "invoice"

# Run tests, stop on first failure
pytest -x

# Run last 10 failures
pytest --lf --ff
```

### Coverage Report

```bash
# Generate coverage report
pytest --cov=finance --cov=procurement --cov=core --cov-report=html

# View report
open htmlcov/index.html

# Coverage by module
pytest --cov=. --cov-report=term-missing
```

---

## Coverage Goals

### Phase 1: Foundation (30 days)

**Target**: 50% coverage

Priority modules:
- Core utilities and base classes
- Finance: Invoice models and serializers
- Procurement: PurchaseOrder models
- Auth: Authentication and permissions

```bash
pytest --cov=finance --cov=core --cov=procurement --cov=authmanagement
# Target: 50% total coverage
```

### Phase 2: Enhancement (60 days)

**Target**: 80% coverage

Add tests for:
- Delivery note workflow
- Invoice payment workflow
- Procurement approval workflow
- HRM payroll calculations
- API endpoint tests

### Phase 3: Optimization (90 days)

**Target**: 90%+ coverage

- Edge cases and error scenarios
- Performance tests
- Integration tests
- End-to-end tests

---

**Document Version**: 1.0  
**Status**: Implementation Ready  
**Estimated Effort**: 80-120 hours over 90 days
