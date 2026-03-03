# Cross-Module Gaps, Testing & Implementation Guide

## Executive Summary

This document identifies critical gaps across the four audited modules (Finance, Inventory, Procurement, Manufacturing), provides testing strategies, and outlines implementation priorities.

**Total Estimated Effort**: 900-1,200 hours over 4-5 months

---

## Part 1: Critical Cross-Module Issues

### Issue #1: Inventory Stock Level Synchronization (CRITICAL)
**Affected Modules**: Finance, Inventory, Manufacturing, Procurement  
**Severity**: CRITICAL  
**Effort**: 30-40 hours  
**Timeline**: Weeks 1-2

**Problem**:
- StockInventory.stock_level is denormalized integer (not synced with transactions)
- Manufacturing batches create stock without transaction records
- Procurement receives don't update inventory
- Invoice line items don't track fulfillment

**Impact**:
```
Invoice created for 100 units
├─ Inventory shows: 100 units in stock
├─ Manufacturing produces batch of 50
│  └─ Inventory NOT updated ❌
├─ Procurement receives 50
│  └─ Inventory manually updated (if at all)
└─ Final Reality: Need manual reconciliation
```

**Solution**:
```python
# Create StockTransactionHandler
class StockTransactionHandler:
    @classmethod
    def create_transaction(cls, stock_item, transaction_type, quantity, reference):
        transaction = StockTransaction.objects.create(
            stock_item=stock_item,
            transaction_type=transaction_type,
            quantity=quantity,
            reference_number=reference
        )
        # Auto-update denormalized stock_level
        stock_item.stock_level = stock_item.calculate_stock_from_transactions()
        stock_item.save(update_fields=['stock_level'])
        return transaction
    
    @classmethod
    def calculate_stock_from_transactions(stock_item):
        return stock_item.stocktransaction_set.aggregate(
            total=Sum('quantity')
        )['total'] or 0
```

**Action Items**:
- [ ] Add transaction hook in ProductionBatch.mark_completed()
- [ ] Add transaction hook in PurchaseOrder.mark_received()
- [ ] Add transaction hook in Invoice.clone_or_fulfill()
- [ ] Create daily reconciliation task
- [ ] Add stock_level_verified_at timestamp
- [ ] Create data migration to sync existing records

---

### Issue #2: No Order-to-Cash Integration (CRITICAL)
**Affected Modules**: Finance, Inventory, Procurement, Manufacturing  
**Severity**: CRITICAL  
**Effort**: 40-50 hours  
**Timeline**: Weeks 2-4

**Problem**:
- Procurement PO not linked to Manufacturing demand
- Manufacturing produces without linking to invoices
- Invoice fulfillment not tracked
- No order-to-fulfillment workflow

**Current Flow** ❌:
```
Manufacturing Requisition
        ↓ (not linked)
Procurement PO
        ↓ (not linked)
Inventory Stock
        ↓ (not linked)
Invoice to Customer
        ↓ (not linked)
Stock Deduction
```

**Desired Flow** ✓:
```
Sales Order (from Invoice line items)
    ↓ Creates
Manufacturing Requisition (demands)
    ↓ Creates
Procurement PO (to fulfill demands)
    ↓ Creates
Stock Receipt (StockTransaction)
    ↓ Updates
Inventory Stock
    ↓ Auto-allocated to
Sales Order
    ↓ Creates
Delivery Note + Invoice Fulfillment
    ↓ Triggers
Payment Processing
```

**Solution Components**:
1. Link Invoice items to manufacturing demand
2. Link manufacturing output to inventory allocation
3. Track fulfillment per invoice line item
4. Create automated supply chain workflow

---

### Issue #3: Approval Workflow Enforcement (CRITICAL)
**Affected Modules**: Finance, Procurement, Manufacturing  
**Severity**: CRITICAL  
**Effort**: 40-50 hours  
**Timeline**: Weeks 3-5

**Problem**:
- Approval fields exist but not validated
- Can bypass approval steps
- No status machine enforcement
- Rejection reasons not tracked

**Current State** ❌:
```python
invoice = Invoice.objects.create(
    status='approved'  # Can set directly!
)

# Can create without going through approval
purchase_order.status = 'ordered'  # Allowed even if unauthorized
```

**Solution**:
```python
# Create formal WorkflowStateMachine
class WorkflowStateMachine:
    ALLOWED_TRANSITIONS = {
        'draft': ['submitted', 'cancelled'],
        'submitted': ['pending_approval', 'rejected', 'cancelled'],
        'pending_approval': ['approved', 'rejected'],
        'approved': ['ordered', 'rejected'],
        'ordered': ['received', 'cancelled'],
    }
    
    @classmethod
    def validate_transition(cls, from_state, to_state, user, required_roles):
        # Validate user has authority
        # Validate state transition allowed
        # Record approval
        pass
    
    @classmethod
    def record_rejection(cls, obj, reason, notes):
        # Create ApprovalRecord for rejection
        # Record reason code
        # Create audit trail
        pass
```

**Action Items**:
- [ ] Create ApprovalRule model (amount thresholds, roles)
- [ ] Create ApprovalRecord model (track each step)
- [ ] Implement pre_save validation
- [ ] Create status transition endpoints
- [ ] Add rejection reason recording
- [ ] Create approval history view

---

### Issue #4: Payment Integration Gaps (HIGH)
**Affected Modules**: Finance, Procurement  
**Severity**: HIGH  
**Effort**: 30-40 hours  
**Timeline**: Weeks 4-6

**Problems**:
- Invoice payments not matched to PO/tax invoices
- No three-way match (PO/Receipt/Invoice)
- No duplicate payment prevention
- No overpayment validation

**Solution**:
```python
class PaymentMatcher:
    @classmethod
    def match_invoice_to_po(cls, invoice, po):
        """Verify PO matches supplier invoice"""
        if invoice.supplier != po.supplier:
            raise ValidationError("Supplier mismatch")
        
        po_total = po.items.aggregate(Sum('total'))['total__sum']
        if abs(float(invoice.total) - float(po_total)) > 0.01:
            raise ValidationError("Amount mismatch")
        
        return PaymentMatch.objects.create(
            invoice=invoice,
            po=po,
            match_status='verified'
        )
    
    @classmethod
    def validate_payment(cls, payment, invoice):
        """Prevent overpayment/duplicate"""
        remaining_balance = invoice.balance_due
        if payment.amount > remaining_balance:
            raise ValidationError(f"Overpayment: {payment.amount} > {remaining_balance}")
        
        # Check for duplicate reference
        if Payment.objects.filter(reference_number=payment.reference_number).exists():
            raise ValidationError("Duplicate payment reference")
```

**Action Items**:
- [ ] Create PaymentMatch model
- [ ] Create three-way match validator
- [ ] Add duplicate payment prevention
- [ ] Implement overpayment validation
- [ ] Create payment reconciliation report

---

### Issue #5: Raw Material Classification & Costing (HIGH)
**Affected Modules**: Inventory, Manufacturing, Finance  
**Severity**: HIGH  
**Effort**: 25-30 hours  
**Timeline**: Weeks 2-4

**Problem**:
- Raw materials mixed with finished products in StockInventory
- No cost flow assumption (FIFO/LIFO/Weighted Average)
- Manufacturing costs not integrated with formula system
- Can't calculate product COGS

**Solution**:
```python
# Enforce raw material distinction
class StockInventory(Model):
    is_raw_material = BooleanField()
    
    def save(self, *args, **kwargs):
        # Validate service products don't have stock
        # If is_raw_material, ensure product.product_type == 'raw_material'
        super().save(*args, **kwargs)

# Track cost flow
class InventoryValuation:
    METHODS = ['FIFO', 'LIFO', 'WEIGHTED_AVERAGE']
    
    @classmethod
    def calculate_cogs(cls, stock_item, quantity, method='FIFO'):
        """Use cost flow assumption to value inventory"""
        if method == 'FIFO':
            return cls._fifo_cogs(stock_item, quantity)
        elif method == 'WEIGHTED_AVERAGE':
            return cls._weighted_average_cogs(stock_item, quantity)
    
    @classmethod
    def _fifo_cogs(cls, stock_item, quantity):
        # Get oldest transactions
        transactions = StockTransaction.objects.filter(
            stock_item=stock_item,
            transaction_type='PURCHASE'
        ).order_by('transaction_date')
        
        total_cost = 0
        remaining = quantity
        for txn in transactions:
            if remaining <= 0:
                break
            units_to_take = min(txn.quantity, remaining)
            total_cost += units_to_take * txn.cost_per_unit
            remaining -= units_to_take
        return total_cost
```

**Action Items**:
- [ ] Add product_type validation to Products
- [ ] Update StockInventory validation
- [ ] Create InventoryValuation engine
- [ ] Implement FIFO/LIFO/Weighted Average
- [ ] Link manufacturing formula to cost calculation
- [ ] Create COGS reporting

---

## Part 2: Module-Specific Implementation Priorities

### Finance Module - Priority List

| Priority | Issue | Effort | Timeline |
|----------|-------|--------|----------|
| CRITICAL | Stock synchronization (shared) | 30 | W1-2 |
| CRITICAL | Approval workflow enforcement (shared) | 40 | W3-5 |
| CRITICAL | Payment validation & matching (shared) | 30 | W4-6 |
| HIGH | Email/notification integration | 20 | W6-7 |
| HIGH | PDF generation enhancement | 20 | W7-8 |
| HIGH | Recurring invoice automation | 20 | W8-9 |
| MEDIUM | Currency & exchange rate history | 15 | W9-10 |
| MEDIUM | Test expansion (40 tests) | 40 | W2-13 (parallel) |
| **Total** | | **215** | ~13 weeks |

### Inventory Module - Priority List

| Priority | Issue | Effort | Timeline |
|----------|-------|--------|----------|
| CRITICAL | Stock level synchronization | 30 | W1-2 |
| HIGH | Reorder point automation | 20 | W3-4 |
| HIGH | Transfer integration | 20 | W3-4 |
| HIGH | Cost tracking & valuation | 25 | W4-5 |
| MEDIUM | Stock reconciliation framework | 15 | W6-7 |
| MEDIUM | Expiry/batch tracking | 15 | W7-8 |
| MEDIUM | Multi-location optimization | 15 | W8-9 |
| MEDIUM | Test expansion (40 tests) | 40 | W2-13 (parallel) |
| **Total** | | **180** | ~13 weeks |

### Procurement Module - Priority List

| Priority | Issue | Effort | Timeline |
|----------|-------|--------|----------|
| CRITICAL | Workflow state machine | 40 | W3-5 |
| CRITICAL | Requisition-PO relationship fix | 15 | W2-3 |
| HIGH | Partial receives & GRN | 20 | W4-5 |
| HIGH | RFQ & quote system | 20 | W6-7 |
| HIGH | Payment integration | 15 | W4-6 |
| MEDIUM | Supplier performance tracking | 15 | W7-8 |
| MEDIUM | Contract management | 15 | W8-9 |
| MEDIUM | Approval rules engine | 20 | W8-10 |
| MEDIUM | Test expansion (40 tests) | 40 | W2-13 (parallel) |
| **Total** | | **200** | ~13 weeks |

### Manufacturing Module - Priority List

| Priority | Issue | Effort | Timeline |
|----------|-------|--------|----------|
| CRITICAL | Raw material classification | 15 | W2-3 |
| CRITICAL | Batch-to-stock integration | 25 | W3-4 |
| CRITICAL | Raw material usage consolidation | 15 | W2-3 |
| HIGH | Quality control standards | 15 | W5-6 |
| HIGH | Batch costing engine | 20 | W5-6 |
| MEDIUM | Yield & waste tracking | 15 | W7-8 |
| MEDIUM | Equipment tracking | 15 | W7-8 |
| MEDIUM | Formula version comparison | 10 | W8-9 |
| MEDIUM | Test expansion (30 tests) | 30 | W2-13 (parallel) |
| **Total** | | **160** | ~13 weeks |

---

## Part 3: Integrated Testing Strategy

### Testing Pyramid

```
                    △ API Tests (10%)
                   △△ Integration Tests (30%)
                 △△△△ Unit Tests (60%)
```

### Unit Test Coverage Targets

**Finance Module** (40 tests, ~80 hours):
```
1. Invoice Creation (5 tests)
   - Basic creation
   - Auto-number generation
   - Due date calculation from payment terms
   - Status validation
   - Balance due calculation

2. Payment Recording (5 tests)
   - Basic payment
   - Partial payment
   - Overpayment prevention
   - Duplicate prevention
   - Balance update

3. Email Tracking (5 tests)
   - Log creation
   - Bounce handling
   - Open tracking
   - Retry logic

4. Approval Workflow (8 tests)
   - Status transitions
   - Approval routing
   - Rejection with reason
   - Escalation

5. Tax & Expense (5 tests)
   - Tax calculation
   - Recurring expense generation
   - Category validation
   - Payment linking

6. Account Management (7 tests)
   - Account creation
   - Balance tracking
   - Multi-currency
   - Status changes
```

**Inventory Module** (40 tests, ~80 hours):
```
1. Stock Level Management (8 tests)
   - Creation with defaults
   - Stock level sync from transactions
   - Reorder level triggering
   - Availability status

2. Stock Transactions (8 tests)
   - Transaction creation
   - Multiple types (PURCHASE, SALE, etc)
   - Negative quantities
   - Reference linking

3. Stock Transfers (6 tests)
   - Creation of transfer
   - Status progression
   - Partial receives
   - Stock deduction

4. Stock Adjustments (6 tests)
   - Adjustment creation
   - Approval workflow
   - Variance calculation
   - Reason tracking

5. Valuation Methods (8 tests)
   - FIFO costing
   - LIFO costing
   - Weighted average
   - Batch tracking
```

**Procurement Module** (40 tests, ~80 hours):
```
1. Purchase Order Management (8 tests)
   - Creation from requisition
   - Auto-number generation
   - Supplier validation
   - Budget checking

2. Approval Workflow (10 tests)
   - Multi-step approvals
   - Authority validation
   - Rejection handling
   - Escalation

3. Requisition Processing (8 tests)
   - Creation and submission
   - Approval routing
   - PO creation
   - Item allocation

4. Receiving & Matching (8 tests)
   - Partial receives
   - Three-way match
   - Discrepancy handling
   - Invoice matching

5. Supplier Management (6 tests)
   - Performance tracking
   - Rating calculation
   - Contract linking
   - Payment terms
```

**Manufacturing Module** (30 tests, ~60 hours):
```
1. Product Formula (8 tests)
   - Formula creation
   - Ingredient management
   - Version control
   - Costing calculation

2. Production Batches (10 tests)
   - Batch creation
   - Status transitions
   - Resource consumption
   - Output tracking

3. Quality Control (6 tests)
   - Check creation
   - Pass/fail validation
   - Specification limits
   - Result recording

4. Costing (6 tests)
   - Labor cost
   - Overhead allocation
   - Cost per unit
   - Variance analysis
```

### Integration Test Scenarios

**Scenario 1: Order-to-Cash** (~20 hours):
```
1. Sales Order Created
   └─ Invoice generated
   └─ Inventory allocated (if in stock)
   └─ Delivery note created
   └─ Stock deducted on fulfillment
   └─ Payment recorded
   └─ Account balance updated
```

**Scenario 2: Procurement-to-Payment** (~20 hours):
```
1. Manufacturing Requisition
   └─ Procurement request created
   └─ Multi-step approvals
   └─ Purchase order created
   └─ Stock received
   └─ Three-way match
   └─ Payment processed
```

**Scenario 3: Manufacturing-to-Sales** (~15 hours):
```
1. Manufacturing requisition for materials
   └─ Procurement creates PO
   └─ Stock received
   └─ Manufacturing batch created
   └─ Raw materials consumed
   └─ Quality checks performed
   └─ Finished goods to stock
   └─ Inventory updated
   └─ Available for sales
```

### API Endpoint Tests

**Finance Endpoints** (~20 hours):
```
- POST /api/invoices/ (create)
- GET /api/invoices/ (list + filters)
- GET /api/invoices/{id}/ (retrieve)
- POST /api/invoices/{id}/record_payment/ (payment)
- POST /api/invoices/{id}/mark_sent/ (send)
- GET /api/invoices/{id}/download_pdf/ (PDF)
- POST /api/payments/ (create payment)
- All error scenarios
```

**Inventory Endpoints** (~20 hours):
```
- POST /api/stock-inventory/ (create)
- GET /api/stock-inventory/ (list + filters)
- POST /api/stock-transactions/ (log transaction)
- POST /api/stock-transfers/ (create transfer)
- GET /api/stock-transfers/{id}/receive/ (partial receive)
- POST /api/stock-adjustments/ (create adjustment)
- All error scenarios
```

**Procurement Endpoints** (~20 hours):
```
- POST /api/purchase-orders/ (create)
- GET /api/purchase-orders/ (list)
- POST /api/purchase-orders/{id}/approve/ (approve)
- POST /api/purchase-orders/{id}/mark_received/ (receive)
- POST /api/requisitions/ (create requisition)
- All approval workflows
```

**Manufacturing Endpoints** (~15 hours):
```
- POST /api/formulas/ (create formula)
- POST /api/production-batches/ (create batch)
- POST /api/production-batches/{id}/start/ (start)
- POST /api/production-batches/{id}/complete/ (complete)
- POST /api/quality-checks/ (create check)
- All error scenarios
```

---

## Part 4: Implementation Phases

### Phase 0: Foundation (Weeks 1-2) - 40 hours

**Sprint 1: Stock Synchronization**
- Create StockTransactionHandler
- Add transaction hooks
- Create reconciliation task
- Deploy data migration
- **Tests**: 10 unit tests

**Sprint 2: Base Workflow Framework**
- Create WorkflowStateMachine base class
- Create ApprovalRule model
- Create ApprovalRecord model
- **Tests**: 5 unit tests

---

### Phase 1: Critical Fixes (Weeks 3-6) - 150 hours

**Sprint 3-4: Approval Workflows** (40 hours)
- Implement all module approval workflows
- Add rejection handling
- Create approval routing
- **Tests**: 20 integration tests

**Sprint 4-5: Payment Integration** (30 hours)
- Create three-way matcher
- Add overpayment validation
- Implement duplicate prevention
- **Tests**: 15 tests (unit + integration)

**Sprint 5-6: Raw Material Classification** (25 hours)
- Update validation rules
- Create costing engine
- Implement FIFO/LIFO
- **Tests**: 15 tests

**Sprint 6: Stock Transfer & Inventory Integration** (30 hours)
- Complete transfer integration
- Add GRN creation
- Implement reconciliation
- **Tests**: 15 tests

**Sprint 6: Manufacturing Integration** (25 hours)
- Link batch completion to stock
- Create RawMaterialUsage consolidation
- Implement batch-to-product tracking
- **Tests**: 10 tests

---

### Phase 2: High Priority Features (Weeks 7-10) - 180 hours

**Sprint 7-8: Quality Control & Costing** (40 hours)
- Implement quality standards
- Create costing engine
- Add variance tracking
- **Tests**: 20 tests

**Sprint 8-9: Advanced Inventory Features** (40 hours)
- Reorder point automation
- Expiry/batch tracking
- Cost valuation methods
- **Tests**: 20 tests

**Sprint 9-10: Procurement RFQ System** (40 hours)
- Create RFQ model
- Implement quote system
- Add supplier comparison
- **Tests**: 20 tests

**Sprint 10: Email/Notification Integration** (20 hours)
- Connect to SendGrid/Mailgun
- Implement scheduled sends
- Add bounce handling
- **Tests**: 15 tests

**Sprint 10: PDF & Reporting** (40 hours)
- Enhanced PDF templates
- Custom branding
- QR codes
- **Tests**: 15 tests

---

### Phase 3: Medium Priority Features (Weeks 11-13) - 150 hours

**Sprint 11-12: Analytics & Reporting** (60 hours)
- Supplier performance dashboard
- Manufacturing analytics
- Inventory valuation reports
- **Tests**: 20 tests

**Sprint 12-13: Test Expansion** (90 hours)
- Expand to 80%+ coverage
- Edge case testing
- Performance testing
- **Tests**: 40+ new tests

---

## Part 5: Testing Checklist

### Pre-Launch Testing Checklist

#### Data Integrity Tests
- [ ] Stock level matches sum of transactions
- [ ] No orphaned invoices without customer
- [ ] All payments matched to source document
- [ ] No duplicate payment references
- [ ] All manufacturing batches linked to formula version

#### Workflow Tests
- [ ] Can't bypass approval steps
- [ ] Rejection properly recorded with reason
- [ ] Status transitions only allowed after approval
- [ ] Escalation works after timeout
- [ ] Rejection reverses all dependent records

#### Integration Tests
- [ ] Requisition → PO → Stock → Invoice full flow
- [ ] Payment matching works across modules
- [ ] Inventory allocation prevents overselling
- [ ] Manufacturing consumes from correct inventory
- [ ] Cost calculations consistent

#### Performance Tests
- [ ] List endpoints <1 second for 10,000 records
- [ ] Complex queries use select_related/prefetch_related
- [ ] No N+1 query problems
- [ ] Pagination works for large datasets
- [ ] Bulk operations (imports) <1 minute for 1000 records

#### Security Tests
- [ ] Users can't view other company's data
- [ ] Invoices can't be modified after approval
- [ ] Only authorized users can approve
- [ ] Payments can't be reversed without reason
- [ ] Formulas have proper access control

#### Error Handling Tests
- [ ] All ValidationError have user-friendly messages
- [ ] All 4xx errors return consistent format
- [ ] Database errors don't expose internal details
- [ ] Payment failures have clear messages
- [ ] Stock shortages clearly communicated

---

## Part 6: Quick Reference - Gap Summary Table

| # | Module | Gap | Severity | Effort | Phase | Priority |
|---|--------|-----|----------|--------|-------|----------|
| 1 | Finance | Invoice-DeliveryNote integration | CRITICAL | 20 | P0 | Q1 |
| 2 | Finance | Payment validation | CRITICAL | 30 | P1 | Q1 |
| 3 | Finance | Email integration | HIGH | 20 | P2 | Q2 |
| 4 | Finance | Recurring invoices | HIGH | 20 | P2 | Q2 |
| 5 | Finance | Test coverage | CRITICAL | 40 | All | Q1-Q3 |
| 6 | Inventory | Stock sync | CRITICAL | 30 | P0 | Q1 |
| 7 | Inventory | Reorder automation | HIGH | 20 | P2 | Q1 |
| 8 | Inventory | Cost valuation | HIGH | 25 | P1 | Q1 |
| 9 | Inventory | Multi-location | MEDIUM | 15 | P3 | Q2 |
| 10 | Inventory | Test coverage | CRITICAL | 40 | All | Q1-Q3 |
| 11 | Procurement | Workflow enforcement | CRITICAL | 40 | P1 | Q1 |
| 12 | Procurement | Partial receives | HIGH | 20 | P1 | Q1 |
| 13 | Procurement | RFQ system | MEDIUM | 20 | P2 | Q2 |
| 14 | Procurement | Payment matching | HIGH | 15 | P1 | Q1 |
| 15 | Procurement | Test coverage | CRITICAL | 40 | All | Q1-Q3 |
| 16 | Manufacturing | Raw material classification | CRITICAL| 15 | P0 | Q1 |
| 17 | Manufacturing | Batch-to-stock | CRITICAL | 25 | P0 | Q1 |
| 18 | Manufacturing | Quality standards | HIGH | 15 | P2 | Q1 |
| 19 | Manufacturing | Batch costing | HIGH | 20 | P2 | Q1 |
| 20 | Manufacturing | Test coverage | CRITICAL | 30 | All | Q1-Q3 |

---

## Part 7: Success Metrics

### Code Quality Metrics
- [ ] Test coverage: 80%+ for all modules
- [ ] All critical paths covered
- [ ] Zero high-severity security issues
- [ ] API response times: <1 second (p95)
- [ ] Database queries optimized (no N+1)

### Functional Metrics
- [ ] Invoice-to-fulfillment fully integrated
- [ ] 100% payment matching success rate
- [ ] Zero stock level discrepancies
- [ ] All approval workflows enforced
- [ ] Manufacturing production fully audited

### Performance Metrics
- [ ] List endpoints handle 10K+ records
- [ ] Bulk imports <1 minute for 1000 records
- [ ] Approval workflow <5 seconds
- [ ] Report generation <10 seconds
- [ ] Stock calculations real-time

### User Experience Metrics
- [ ] 0 critical production incidents
- [ ] <1% data integrity issues
- [ ] 100% approval routing success
- [ ] <2% validation error rate
- [ ] Clear error messages on 100% of failures

---

## Conclusion

**Estimated Total Effort**: 900-1,200 hours over 4-5 months

**Recommended Team**:
- 2-3 Backend Developers (full-time)
- 1 QA Engineer (full-time)  
- 1 Tech Lead (part-time)
- 1 Database Admin (part-time)

**Success Factors**:
1. Complete Phase 0 & 1 before any releases
2. Comprehensive testing at each phase
3. Regular integration testing
4.Automated testing on CI/CD
5. Performance testing throughout
6. Security review at each phase

