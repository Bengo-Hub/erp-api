# Workflow Implementation Guide

**Document Date**: March 1, 2026  
**Version**: 1.0  
**Status**: Implementation Ready

---

## Table of Contents

1. [Workflow Architecture](#workflow-architecture)
2. [State Machine Patterns](#state-machine-patterns)
3. [Delivery Note Workflow](#delivery-note-workflow)
4. [Invoice Workflow](#invoice-workflow)
5. [Procurement Workflow](#procurement-workflow)
6. [Workflow Implementation Code](#workflow-implementation-code)
7. [Validation Rules](#validation-rules)
8. [Error Handling](#error-handling)

---

## Workflow Architecture

### Design Pattern: State Machine

We implement workflows using a state machine pattern with:
- **Explicit State Definitions**: Enumerated status values
- **Transition Rules**: Define which transitions are allowed
- **Validators**: Check if transition can occur
- **Handlers**: Execute logic when transition happens
- **Audit Trail**: Log all state changes

### Workflow Levels

```
Level 1: Document Creation (Draft)
         ↓
Level 2: Processing (Pending, In Progress)
         ↓
Level 3: Completion (Delivered, Paid, Received)
         ↓
Level 4: Post-Processing (Reconciled, Archived)
```

---

## State Machine Patterns

### Pattern 1: Simple Linear Workflow
```
Draft → Pending → Complete → Archived
```

**Example**: Delivery notes

**Use Case**: Single path with no branching

### Pattern 2: Conditional Branching
```
      ┌─→ Approved → Confirmed
      │
Submitted
      │
      └─→ Rejected → Cancelled
```

**Example**: Purchase orders with approval

**Use Case**: Multiple outcomes based on condition

### Pattern 3: Cyclical Workflow
```
Draft → Active → On Hold → Active → Completed
```

**Example**: Recurring invoices

**Use Case**: Can return to previous states

### Pattern 4: Complex Workflow
```
Draft → Submitted → Approved → Ordered → Partial Received → Fully Received → Reconciled
                        ↓                                                        ↓
                      Rejected ────────────────────────────────────────────→ Cancelled
```

**Example**: Procurement process

**Use Case**: Multiple paths, multiple conditions

---

## Delivery Note Workflow

### Current State (Incomplete)
```
Draft → Pending Delivery → In Transit → Delivered
                       ↓
              Partially Delivered
```

### Enhanced Workflow (Recommended)
```
       ┌──────────────────────────────────┐
       │                                  │
       ↓                                  ↓
Draft ──→ Confirmed → Ready for Pickup → In Transit → Delivered → Signed
            ↓                                             ↓
            Cancelled                          Partially Delivered ──→ Final
```

### Detailed State Diagram

```
state Draft {
    [*] --> Draft
    Draft --> Cancelled: cancel()
    Draft --> Confirmed: confirm()
}

state Confirmed {
    Confirmed --> ReadyForPickup: prepare()
    Confirmed --> Cancelled: cancel()
}

state ReadyForPickup {
    ReadyForPickup --> InTransit: dispatch()
    ReadyForPickup --> Cancelled: cancel()
}

state InTransit {
    InTransit --> Delivered: confirm_receipt()
    InTransit --> PartiallyDelivered: partial_delivery()
}

state PartiallyDelivered {
    PartiallyDelivered --> InTransit: continue_delivery()
    PartiallyDelivered --> Delivered: final_delivery()
    PartiallyDelivered --> Cancelled: cancel()
}

state Delivered {
    Delivered --> Signed: add_signature()
    Delivered --> [*]
}

state Cancelled {
    Cancelled --> [*]
}
```

### Workflow Code Example
```python
class DeliveryNoteWorkflow:
    """State machine for delivery notes"""
    
    # Valid transitions
    TRANSITIONS = {
        'draft': ['confirmed', 'cancelled'],
        'confirmed': ['ready_for_pickup', 'cancelled'],
        'ready_for_pickup': ['in_transit', 'cancelled'],
        'in_transit': ['delivered', 'partially_delivered', 'cancelled'],
        'partially_delivered': ['in_transit', 'delivered', 'cancelled'],
        'delivered': ['signed'],
        'signed': [],
        'cancelled': [],
    }
    
    @staticmethod
    def can_transition(current_status, target_status):
        """Check if transition is allowed"""
        allowed = DeliveryNoteWorkflow.TRANSITIONS.get(current_status, [])
        return target_status in allowed
    
    @staticmethod
    def validate_transition(delivery_note, target_status):
        """Validate if transition is possible"""
        current = delivery_note.status
        
        # Check if transition is defined
        if not DeliveryNoteWorkflow.can_transition(current, target_status):
            raise WorkflowException(
                f"Cannot transition from {current} to {target_status}"
            )
        
        # Check state-specific conditions
        if target_status == 'confirmed':
            if not delivery_note.delivery_address:
                raise WorkflowException(
                    "Delivery address is required to confirm"
                )
        
        if target_status == 'in_transit':
            if not delivery_note.driver_name:
                raise WorkflowException(
                    "Driver name is required"
                )
        
        if target_status in ['delivered', 'partially_delivered']:
            if not delivery_note.received_by:
                raise WorkflowException(
                    "Receiver name is required"
                )
        
        return True
    
    @staticmethod
    def execute_transition(delivery_note, target_status, **kwargs):
        """Execute state transition"""
        current = delivery_note.status
        
        # Validate
        DeliveryNoteWorkflow.validate_transition(delivery_note, target_status)
        
        # Pre-transition hooks
        delivery_note._pre_transition(current, target_status)
        
        # Update status
        delivery_note.status = target_status
        delivery_note.save()
        
        # Post-transition hooks
        delivery_note._post_transition(current, target_status)
        
        # Log to audit trail
        AuditTrail.log(
            operation=AuditTrail.UPDATE,
            module='finance',
            entity_type='DeliveryNote',
            entity_id=delivery_note.id,
            changes={'status': target_status},
            reason=f'Transitioned from {current} to {target_status}'
        )
        
        return delivery_note
```

### Transition Handlers

```python
class DeliveryNote(BaseOrder):
    def _pre_transition(self, current_status, target_status):
        """Pre-transition validation and setup"""
        if target_status == 'in_transit':
            # Verify driver details
            if not self.driver_name or not self.vehicle_number:
                raise ValidationError("Driver and vehicle info required")
    
    def _post_transition(self, current_status, target_status):
        """Post-transition actions"""
        if target_status == 'delivered':
            self.received_at = timezone.now()
            self.save(update_fields=['received_at'])
            
            # Update invoice fulfillment status
            if self.source_invoice:
                self.source_invoice.update_fulfillment_status()
            
            # Send notification
            send_delivery_confirmation_email(self)
        
        elif target_status == 'cancelled':
            # Cancel related payment
            if self.source_invoice:
                self.source_invoice.update_fulfillment_status()
```

---

## Invoice Workflow

### Current State (Implicit)
```
Draft → Sent → (Optional Approval) → Awaiting Payment → Paid
(with optional Cancelled/Void)
```

### Recommended Enhanced State Machine

```
Draft ──→ Pending Approval ──→ Approved ──→ Sent ──→ Awaiting Payment ──→ Paid ──→ Reconciled
  ↓           ↓                              ↓           ↓                   ↓
Cancel     Reject                          Cancel    Overdue            Archived
                                                         ↓
                                                   Payment Received
                                                         │
                                                         ↓
                                                   Partially Paid
```

### State Definitions

| State | Description | Valid Transitions |
|-------|-------------|------------------|
| `draft` | Invoice created, not sent | sent, cancelled, pending_approval |
| `pending_approval` | Awaiting approval | approved, rejected, cancelled |
| `approved` | Approved for sending | sent, cancelled |
| `sent` | Sent to customer | awaiting_payment, viewed, cancelled |
| `viewed` | Customer viewed invoice | awaiting_payment, cancelled |
| `awaiting_payment` | Awaiting payment | partially_paid, paid, overdue, cancelled |
| `partially_paid` | Partial payment received | awaiting_payment, paid, overdue, cancelled |
| `paid` | Fully paid | reconciled, cancelled |
| `overdue` | Past due date | partially_paid, paid, cancelled |
| `cancelled` | Invoice cancelled | - |
| `void` | Invoice voided | - |
| `reconciled` | Fully reconciled | archived |
| `archived` | Archived for history | - |

---

## Procurement Workflow

### Current State (In workflows.py)

File: `procurement/workflows.py`

Likely existing transitions:
```
Draft → Submitted → Approved → Ordered → Received
           ↓
        Rejected
```

### Recommended Enhanced Workflow

```
Draft ────→ Submitted ────→ Approved ────→ Ordered ────→ Partial Received ────→ Received ────→ Invoiced
 ↓              ↓              ↓               ↓                ↓                    ↓              ↓
Cancel        Reject       Cancel          Cancel           Cancel               Cancel        Reconciled
```

### Key Validations

```python
class ProcurementWorkflow:
    @staticmethod
    def validate_submitted(po):
        """Validate before submitting"""
        if not po.items.exists():
            raise ValidationError("PO must have line items")
        if po.total <= 0:
            raise ValidationError("PO total must be positive")
        return True
    
    @staticmethod
    def validate_approved(po):
        """Validate before approving"""
        # Check approval authority
        if not user_can_approve(po.total):
            raise ValidationError("Insufficient approval authority")
        # Check budget
        if po.total > po.approved_budget:
            raise ValidationError("Exceeds approved budget")
        return True
    
    @staticmethod
    def validate_ordered(po):
        """Validate before ordering"""
        # Check supplier is active
        if not po.supplier.is_active:
            raise ValidationError("Supplier is not active")
        return True
    
    @staticmethod
    def validate_received(po):
        """Validate before marking received"""
        # Check all items received
        total_items = po.items.aggregate(Sum('quantity'))['quantity__sum']
        received_items = po.items.aggregate(
            Sum('receipt_quantity')
        )['receipt_quantity__sum']
        
        if received_items < total_items:
            raise ValidationError(
                f"Not all items received. "
                f"Received: {received_items}, Expected: {total_items}"
            )
        return True
```

---

## Workflow Implementation Code

### Base Workflow Class

```python
# core/workflows.py

from typing import Dict, List, Callable, Optional
from enum import Enum
from django.core.exceptions import ValidationError
from django.utils import timezone

class WorkflowException(Exception):
    """Custom exception for workflow errors"""
    pass

class Workflow:
    """Base class for workflow state machines"""
    
    # Subclasses must define these
    STATES: Dict[str, str] = {}  # {'status_value': 'Display Name'}
    TRANSITIONS: Dict[str, List[str]] = {}  # {'from_state': ['to_state1', 'to_state2']}
    
    def __init__(self, entity):
        self.entity = entity
    
    def get_current_state(self) -> str:
        """Get current state of entity"""
        return self.entity.status
    
    def get_allowed_transitions(self) -> List[str]:
        """Get list of allowed transitions from current state"""
        current = self.get_current_state()
        return self.TRANSITIONS.get(current, [])
    
    def can_transition(self, target_state: str) -> bool:
        """Check if transition to target state is allowed"""
        allowed = self.get_allowed_transitions()
        return target_state in allowed
    
    def validate_transition(self, target_state: str) -> bool:
        """Override in subclass for custom validation"""
        return True
    
    def execute_transition(self, target_state: str, **kwargs) -> bool:
        """Execute state transition"""
        current = self.get_current_state()
        
        # Validate transition is allowed
        if not self.can_transition(target_state):
            raise WorkflowException(
                f"Cannot transition from {current} to {target_state}. "
                f"Allowed states: {self.get_allowed_transitions()}"
            )
        
        # Validate conditions
        if not self.validate_transition(target_state):
            raise WorkflowException(
                f"Validation failed for transition to {target_state}"
            )
        
        # Pre-transition hook
        self.pre_transition(current, target_state, **kwargs)
        
        # Update status
        self.entity.status = target_state
        self.entity.save()
        
        # Post-transition hook
        self.post_transition(current, target_state, **kwargs)
        
        # Log transition
        self.log_transition(current, target_state)
        
        return True
    
    def pre_transition(self, from_state: str, to_state: str, **kwargs):
        """Override in subclass for pre-transition logic"""
        pass
    
    def post_transition(self, from_state: str, to_state: str, **kwargs):
        """Override in subclass for post-transition logic"""
        pass
    
    def log_transition(self, from_state: str, to_state: str):
        """Log transition to audit trail"""
        from core.audit import AuditTrail
        
        AuditTrail.log(
            operation=AuditTrail.UPDATE,
            module=self.entity._meta.app_label,
            entity_type=self.entity.__class__.__name__,
            entity_id=self.entity.id,
            changes={'status': to_state},
            reason=f'Status changed from {from_state} to {to_state}'
        )
```

### Delivery Note Workflow

```python
# finance/invoicing/workflows.py

from core.workflows import Workflow, WorkflowException
from django.core.exceptions import ValidationError
from django.utils import timezone

class DeliveryNoteWorkflow(Workflow):
    """State machine for delivery notes"""
    
    STATES = {
        'draft': 'Draft',
        'confirmed': 'Confirmed',
        'ready_for_pickup': 'Ready for Pickup',
        'in_transit': 'In Transit',
        'partially_delivered': 'Partially Delivered',
        'delivered': 'Delivered',
        'signed': 'Signed',
        'cancelled': 'Cancelled',
    }
    
    TRANSITIONS = {
        'draft': ['confirmed', 'cancelled'],
        'confirmed': ['ready_for_pickup', 'cancelled'],
        'ready_for_pickup': ['in_transit', 'cancelled'],
        'in_transit': ['delivered', 'partially_delivered', 'cancelled'],
        'partially_delivered': ['in_transit', 'delivered', 'cancelled'],
        'delivered': ['signed'],
        'signed': [],
        'cancelled': [],
    }
    
    def validate_transition(self, target_state: str) -> bool:
        """Validate specific transitions"""
        current = self.get_current_state()
        
        # Confirmed state requires delivery address
        if target_state == 'confirmed':
            if not self.entity.delivery_address:
                raise ValidationError("Delivery address is required")
            if not self.entity.delivery_date:
                raise ValidationError("Delivery date is required")
        
        # In transit requires driver details
        if target_state == 'in_transit':
            if not self.entity.driver_name:
                raise ValidationError("Driver name is required")
            if not self.entity.vehicle_number:
                raise ValidationError("Vehicle number is required")
        
        # Delivered/Partially delivered require receipt details
        if target_state in ['delivered', 'partially_delivered']:
            if not self.entity.received_by:
                raise ValidationError("Receiver name is required")
        
        # Signed requires signature
        if target_state == 'signed':
            if not self.entity.receiver_signature:
                raise ValidationError("Signature is required")
        
        return True
    
    def post_transition(self, from_state: str, to_state: str, **kwargs):
        """Handle post-transition actions"""
        # Update timestamps
        if to_state == 'in_transit':
            # Set dispatch time implicitly
            pass
        
        if to_state in ['delivered', 'partially_delivered']:
            self.entity.received_at = timezone.now()
            self.entity.save(update_fields=['received_at'])
            
            # Update source invoice fulfillment
            if self.entity.source_invoice:
                self.entity.source_invoice.update_fulfillment_status()
            
            # Send notification
            from notifications.models import EmailLog
            # TODO: Send delivery confirmation
        
        elif to_state == 'cancelled':
            # Reset invoice fulfillment for affected items
            if self.entity.source_invoice:
                self.entity.source_invoice.update_fulfillment_status()
```

---

## Validation Rules

### By Workflow Status

#### Delivery Note Validations

| Status | Required Fields | Validations |
|--------|-----------------|-------------|
| draft | - | None |
| confirmed | delivery_address, delivery_date | Address not blank, Date is valid |
| ready_for_pickup | driver_name, vehicle_number | Not blank |
| in_transit | driver_name, vehicle_number | Valid contact info |
| delivered | received_by, received_at | Not blank, timestamp valid |
| signed | receiver_signature | Image file, max 5MB |

#### Invoice Validations

| Status | Required Fields | Validations |
|--------|-----------------|-------------|
| draft | customer, items | Customer valid, items > 0 |
| pending_approval | - | None additional |
| approved | approved_by, approved_at | User valid, timestamp valid |
| sent | recipient_email | Valid email format |
| awaiting_payment | amount_due > 0 | Balance due calculation correct |
| paid | amount_paid >= total | Payment records exist |

---

## Error Handling

### Workflow Exceptions

```python
# In view
try:
    workflow = DeliveryNoteWorkflow(delivery_note)
    workflow.execute_transition('in_transit', initiated_by=request.user)
except WorkflowException as e:
    return Response(
        {'error': str(e), 'code': 'INVALID_STATE_TRANSITION'},
        status=status.HTTP_400_BAD_REQUEST
    )
except ValidationError as e:
    return Response(
        {'error': e.message, 'code': 'VALIDATION_ERROR'},
        status=status.HTTP_400_BAD_REQUEST
    )
```

### Error Response Format

```json
{
    "error": {
        "code": "INVALID_STATE_TRANSITION",
        "message": "Cannot transition from draft to in_transit. Allowed states: [confirmed]",
        "current_state": "draft",
        "allowed_transitions": ["confirmed", "cancelled"],
        "timestamp": "2026-03-01T10:30:00Z"
    }
}
```

---

## Testing Workflow

```python
# tests/test_delivery_note_workflow.py

class DeliveryNoteWorkflowTests(TestCase):
    def setUp(self):
        self.invoice = Invoice.objects.create(...)
        self.delivery_note = DeliveryNote.objects.create(
            source_invoice=self.invoice,
            status='draft'
        )
        self.workflow = DeliveryNoteWorkflow(self.delivery_note)
    
    def test_draft_to_confirmed_valid_transition(self):
        """Test valid transition from draft to confirmed"""
        self.delivery_note.delivery_address = "123 Main St"
        self.delivery_note.delivery_date = timezone.now().date()
        
        self.assertTrue(self.workflow.can_transition('confirmed'))
        self.workflow.execute_transition('confirmed')
        
        self.delivery_note.refresh_from_db()
        self.assertEqual(self.delivery_note.status, 'confirmed')
    
    def test_draft_to_confirmed_missing_address(self):
        """Test transition fails without delivery address"""
        with self.assertRaises(ValidationError):
            self.workflow.execute_transition('confirmed')
    
    def test_invalid_transition(self):
        """Test invalid transition raises exception"""
        with self.assertRaises(WorkflowException):
            self.workflow.execute_transition('delivered')
    
    def test_full_workflow_path(self):
        """Test complete workflow from draft to delivered"""
        path = [
            ('confirmed', {'delivery_address': '123 St', 'delivery_date': timezone.now().date()}),
            ('ready_for_pickup', {}),
            ('in_transit', {'driver_name': 'John', 'vehicle_number': 'ABC-123'}),
            ('delivered', {'received_by': 'Customer', 'received_at': timezone.now()}),
        ]
        
        for target_state, setup_fields in path:
            for field, value in setup_fields.items():
                setattr(self.delivery_note, field, value)
            self.delivery_note.save()
            
            workflow = DeliveryNoteWorkflow(self.delivery_note)
            workflow.execute_transition(target_state)
            self.delivery_note.refresh_from_db()
            self.assertEqual(self.delivery_note.status, target_state)
```

---

## Implementation Checklist

- [ ] Create `core/workflows.py` with base Workflow class
- [ ] Create `finance/invoicing/workflows.py` with DeliveryNoteWorkflow and InvoiceWorkflow
- [ ] Create `procurement/workflows.py` update with enhanced workflow
- [ ] Add workflow validation methods to models
- [ ] Update ViewSets to use workflow for state transitions
- [ ] Create serializers for state transition requests
- [ ] Add comprehensive workflow tests
- [ ] Document workflow in API docs
- [ ] Train team on new workflow system
- [ ] Test in staging environment
- [ ] Deploy to production

---

**Document Version**: 1.0  
**Status**: Ready for Implementation  
**Estimated Effort**: 30-40 hours
