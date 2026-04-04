# Procurement Module - Comprehensive Audit

## Executive Summary

The Procurement module (`procurement/`) manages purchase requisitions, purchase orders, supplier management, purchases, and procurement workflows. It integrates with inventory, finance, and manufacturing modules.

**Module Location**: `procurement/`  
**Submodules**: orders, requisitions, purchases, supplier_performance, contracts, analytics, services  
**Status**: Partially functional with critical workflow gaps  
**Coverage**: ~20% test coverage, urgently needs expansion

---

## Database Schema & Models

### Core Models

#### 1. **PurchaseOrder** (procurement/orders/models.py)
**Extends**: BaseOrder  
**Purpose**: Centralized purchase order management

**Key Fields**:
```
- requisition (OneToOneField to ProcurementRequest, nullable)
  [ISSUE: OneToOne but can be null - should be ForeignKey]
- approved_budget (DecimalField, max_digits=15, decimals=2)
- actual_cost (DecimalField, nullable) - Set after receiving
- delivery_instructions (TextField)
- expected_delivery (DateField, nullable)
- approved_at (DateTimeField, nullable)
- ordered_at (DateTimeField, nullable)
- received_at (DateTimeField, nullable)
- approved_by (ForeignKey to User, nullable)
- approvals (ManyToMany to Approval)
```

**Inherited from BaseOrder**:
- order_number (auto-generated from DocumentNumberService)
- order_type = 'purchase_order' (enforced in save)
- supplier (ForeignKey to Contact)
- branch (ForeignKey to Branch)
- created_by (ForeignKey to User)
- items (via GenericForeignKey to OrderItem)
- subtotal, tax_amount, discount, total
- status - 'draft', 'approved', 'ordered', 'received', 'cancelled'
- created_at, updated_at

**Key Methods**:
- `generate_order_number()` - Uses DocumentNumberService to create LSO0034-150126 format
- `approve_order(approved_by_user)` - Changes status to 'approved'
- `cancel_order(reason)` 
- `mark_as_received(received_by)`

**Workflow Status**:
```
draft → submitted → approved → ordered → received

Possible rejections:
- draft → cancelled
- submitted → rejected (with reason)
```

---

#### 2. **ProcurementRequest** (procurement/requisitions/models.py)
**Purpose**: Internal request to procurement department to source materials

**Key Fields**:
```
- reference_number (CharField, unique)
- status (CharField) - draft, submitted, procurement_review, approved, ordered, cancelled
- requester (ForeignKey to User)
- requesting_department (ForeignKey to Department, nullable)
- reason (TextField) - Why requesting
- budget_allocation (DecimalField, nullable)
- requested_date (DateField)
- required_date (DateField) - When needed
- notes (TextField, nullable)
- created_at (DateTimeField, auto_now_add=True)
- updated_at (DateTimeField, auto_now=True)
```

**Relationships**:
- Has many RequisitionItem records
- Links to single PurchaseOrder (OneToOne relation)
- Has ApprovalRecord entries

**Key Methods**:
- `submit()` - Changes status to 'submitted'
- `approve()` - Marks as approved
- `create_purchase_order()` - Creates linked PurchaseOrder

---

#### 3. **RequisitionItem** (procurement/requisitions/models.py)
**Purpose**: Individual items in a procurement request

**Key Fields**:
```
- requisition (ForeignKey to ProcurementRequest)
- product (ForeignKey to Products, nullable)
- stock_item (ForeignKey to StockInventory, nullable)
- quantity (DecimalField)
- unit (ForeignKey to Unit, nullable)
- estimated_unit_price (DecimalField, nullable)
- approved_quantity (DecimalField, nullable) 
  [ISSUE: Can differ from requested quantity]
- notes (TextField, nullable)
```

**Challenges**:
- ❌ Can't link to both product and stock_item
- ❌ No tracking of approved vs requested quantities
- ❌ Price change between requisition and PO not tracked

---

#### 4. **Purchase** (procurement/purchases/models.py)
**Purpose**: Actual purchase record (supplier invoice)

**Key Fields**:
```
- purchase_number (CharField, unique)
- supplier (ForeignKey to Contact)
- purchase_date (DateField)
- purchase_status (CharField) - draft, ordered, received, cancelled, returned
- payment_status (CharField) - pending, partial, paid
- delivery_address (TextField, nullable)
- expected_delivery_date (DateField, nullable)
- actual_delivery_date (DateField, nullable)
- grand_total (DecimalField)
- currency (CharField, default='KES')
- exchange_rate (DecimalField)
- purchase_note (TextField, nullable)
- received_by (ForeignKey to User, nullable)
- received_at (DateTimeField, nullable)
- created_by (ForeignKey to User)
- created_at (DateTimeField, auto_now_add=True)
- updated_at (DateTimeField, auto_now=True)
```

**Key Methods**:
- `mark_received()` 
- `create_payment_record()`
- `calculate_taxes()`

---

#### 5. **PurchaseItems** (procurement/purchases/models.py)
**Purpose**: Line items in purchase order

**Key Fields**:
```
- purchase (ForeignKey to Purchase)
- stock_item (ForeignKey to StockInventory)
- qty (DecimalField) - Quantity ordered
- qty_received (DecimalField, nullable)
  [ISSUE: Partial receives not tracked]
- unit_price (DecimalField)
- line_total (DecimalField)
- tax_rate (DecimalField, nullable)
- tax_amount (DecimalField, nullable)
```

---

#### 6. **SupplierPerformance** (procurement/supplier_performance/models.py)
**Purpose**: Track supplier metrics and performance

**Key Fields**:
```
- supplier (ForeignKey to Contact)
- on_time_delivery_rate (DecimalField) - Percentage
- quality_score (DecimalField) - 0-100
- communication_score (DecimalField) - 0-100
- price_competitiveness (DecimalField) - 0-100
- total_purchases (DecimalField)
- average_lead_time (IntegerField) - Days
- last_updated (DateTimeField, auto_now=True)
```

---

#### 7. **ProcurementContract** (procurement/contracts/models.py)
**Purpose**: Supplier contracts and agreements

**Key Fields**:
```
- supplier (ForeignKey to Contact)
- contract_number (CharField, unique)
- start_date (DateField)
- end_date (DateField)
- terms_and_conditions (TextField)
- payment_terms (CharField)
- renewal_date (DateField, nullable)
- is_active (BooleanField, default=True)
- contract_value (DecimalField, nullable)
- created_at (DateTimeField, auto_now_add=True)
```

---

## Serializers

### 1. **PurchaseOrderSerializer** (procurement/orders/serializers.py)
**Extends**: BaseOrderSerializer  
**Used for**: Complete PO data

**Key Field Additions**:
- supplier_name (computed from supplier.user)
- requisition_reference (from requisition.reference_number)
- approvals (nested ApprovalSerializer)
- total_paid (computed from po_payments)
- current_approver_id (from approval process)
- pending_approvals_list

---

### 2. **PurchaseOrderListSerializer**
**Used for**: List views with optimized fields

**Includes**:
- id, order_number, requisition_reference
- supplier, supplier_name
- status, total, expected_delivery
- approved_budget, actual_cost
- created_at, currency

---

### 3. **ProcurementRequestSerializer**
**Fields**: All ProcurementRequest fields plus nested RequisitionItems

---

### 4. **PurchaseSerializer**
**Fields**: All Purchase fields with supplier and items nested

---

## ViewSets & API Endpoints

### 1. **PurchaseOrderViewSet** (procurement/orders/views.py)
**Base**: BaseModelViewSet  
**Key Actions**:
- List/Create/Retrieve/Update/Delete POs
- `@action` approve_order
- `@action` cancel_order
- `@action` mark_received
- `@action` download_pdf

---

### 2. **ProcurementRequestViewSet**
**Key Actions**:
- Submit requisition
- Review/approve
- Create purchase order from requisition

---

### 3. **PurchaseViewSet**
**Key Actions**:
- List/Create purchases
- Mark received
- Create payment
- Track delivery

---

### 4. **SupplierPerformanceViewSet**
**Key Actions**:
- View supplier metrics
- Update performance scores
- Generate supplier reports

---

## Workflows & Business Logic

### Current Workflow (procurement/workflows.py)

#### **Requisition → PurchaseOrder → Purchase Workflow**:

```python
1. Manufacturing: initiate_requisition()
   ├─ Create ProcurementRequest (status='draft')
   ├─ Add RequisitionItem records
   └─ Return requisition

2. Manufacturing: submit_for_approval()
   ├─ Change status to 'procurement_review'
   └─ Send notification to procurement

3. Procurement: process_procurement_review()
   ├─ If approved:
   │  ├─ Create BaseOrder
   │  ├─ Copy approved items to Purchase
   │  └─ status='approved'
   └─ If rejected:
      └─ status='rejected'

4. Finance: process_finance_approval()
   ├─ Create Approval record
   ├─ If approved:
   │  ├─ Create actual Purchase
   │  ├─ Add PurchaseItems
   │  └─ status='ordered'
   └─ If rejected:
      └─ status='rejected'
```

**ISSUES WITH CURRENT WORKFLOW**:
- ❌ Mixing BaseOrder and Purchase concepts
- ❌ No proper state machine enforcement
- ❌ Approval tracking incomplete
- ❌ No rejection handling with reason
- ❌ Status transitions not validated
- ❌ No rollback on rejection

---

## Critical Gaps & Issues

### 1. **Workflow Enforcement** (CRITICAL - 30-40 hrs)
**Current State**:
- Workflow logic exists in workflows.py
- Not integrated with models/serializers
- Status transitions not validated

**Problems**:
- ❌ Can set invalid status transitions
- ❌ Can skip approval steps
- ❌ No enforcement of approval authority
- ❌ No rejection reasons recorded

**Solution**:
- Create formal WorkflowStateMachine class
- Add status validators (pre_save hook)
- Link approvals to status transitions
- Record rejection reasons
- Create workflow audit trail

---

### 2. **Requisition-PO Relationship** (HIGH - 15-20 hrs)
**Current State**:
- OneToOne relationship (requisition field)
- But OneToOne can be null
- No handling of multiple POs from one requisition

**Problems**:
- ❌ OneToOne prevents multiple partial POs from requisition
- ❌ Can't split requisition across suppliers
- ❌ No tracking of partial fulfillment

**Solution**:
- Change to ForeignKey (allow multiple POs per requisition)
- Add requisition_item_id to track which items in each PO
- Track partial fulfillment per item

---

### 3. **PO vs Purchase Confusion** (CRITICAL - 20-30 hrs)
**Current State**:
- PurchaseOrder extends BaseOrder (uses generic system)
- Purchase is separate model
- Duplicate concept definitions

**Problems**:
- ❌ Two models for similar concepts
- ❌ Confusion on which to use
- ❌ Data consistency issues
- ❌ Difficult to integrate with invoices

**Solution**:
- Consolidate: PurchaseOrder should be your source of truth
- Purchase should be read-only aggregation
- OR: Purchase should extend BaseOrder for supplier invoices
- Create clear distinctions in docs

---

### 4. **Approval Workflow Incomplete** (HIGH - 20-25 hrs)
**Current State**:
- Approval fields exist
- Simple boolean flags
- No workflow steps

**Problems**:
- ❌ No routing to correct approver
- ❌ No escalation logic
- ❌ No approval deadlines
- ❌ No concurrent approval needs

**Solution**:
- Create ApprovalRule model
- Define who approves based on amount
- Implement escalation after X days
- Support concurrent approvals
- Track approval timeline

---

### 5. **Partial Received Quantities** (HIGH - 15-20 hrs)
**Current State**:
- qty_received field exists
- Not integrated with stock creation
- No validation against qty_ordered

**Problems**:
- ❌ Can receive more than ordered
- ❌ Stock not updated for partial receives
- ❌ No tracking of shortages
- ❌ Can't generate GRN (Goods Receipt Note)

**Solution**:
- Create GRN model for received items
- Validate: qty_received <= qty_ordered
- Auto-create StockTransaction on receive
- Track shortage/excess separately
- Implement three-way match (PO/Receipt/Invoice)

---

### 6. **Supplier Performance Tracking** (MEDIUM - 15-20 hrs)
**Current State**:
- SupplierPerformance model exists
- Fields defined but not calculated
- No history tracking

**Problems**:
- ❌ Metrics not auto-calculated
- ❌ No historical comparison
- ❌ Can't analyze trends
- ❌ Can't alert on declining performance

**Solution**:
- Create metric calculation engine
- Track history (SupplierPerformanceHistory)
- Auto-calculate from transactions
- Create performance dashboard
- Implement alerts for low scores

---

### 7. **No RFQ/Quotation System** (MEDIUM - 20-25 hrs)
**Current State**:
- No Request for Quotation (RFQ)
- No supplier comparison
- No quote approval

**Problems**:
- ❌ Can't compare supplier quotes
- ❌ No procurement transparency
- ❌ Can't select best price
- ❌ No quote expiration tracking

**Solution**:
- Create RFQ model
- Create supplier quote submission
- Implement quote comparison view
- Add quote approval and acceptance
- Link accepted quote to PO

---

### 8. **No Contract Management** (MEDIUM - 15-20 hrs)
**Current State**:
- ProcurementContract model exists
- Not linked to POs
- No terms enforcement

**Problems**:
- ❌ Contract terms not enforced
- ❌ Can buy from non-contracted suppliers
- ❌ No contract expiry alerts
- ❌ No price validation against contract

**Solution**:
- Link POs to contracts
- Validate prices against contract rates
- Alert on contract renewal dates
- Track contract usage/value

---

### 9. **No Payment Integration** (HIGH - 15-20 hrs)
**Current State**:
- payment_status field exists
- No link to Payment model
- No payment terms from contract

**Problems**:
- ❌ Can't track payment status
- ❌ No payment due date calculation
- ❌ Can't match invoice to PO
- ❌ No payment schedule support

**Solution**:
- Create PurchasePayment model
- Link to Payment table
- Implement three-way match
- Add payment term scenarios

---

### 10. **Test Coverage** (CRITICAL - 60-80 hrs)
**Current State**:
- Minimal test coverage (~20%)

**Tests Needed**:
- Requisition creation and submission (10 hrs)
- PO creation from requisition (15 hrs)
- Approval workflow (20 hrs)
- Partial receipts (15 hrs)
- Integration with inventory (20 hrs)
- Supplier performance tracking (10 hrs)

---

## Performance Issues

### 1. **Query Optimization**
- Missing select_related for supplier, approvals
- Missing prefetch_related for items
- No index on (supplier, status)

### 2. **Approval Query N+1**
- Each PO loads all approvals
- Each approval loads approver details
- Need: prefetch_related('approvals__approver')

---

## Data Integrity Issues

### 1. **Constraint Violations**
- Can change status without validation
- Can approve without authority
- Can receive more than ordered

### 2. **Foreign Key Issues**
- supplier deletion orphans POs
- Department deletion orphans requisitions
- No cascade delete handling

---

## Recommended Implementation Roadmap

### Phase 1 (Weeks 1-4): Critical Fixes
1. **Workflow State Machine** (30 hrs)
   - Create formal workflow class
   - Validate status transitions
   - Record approval chain

2. **Requisition-PO Relationship** (15 hrs)
   - Change to ForeignKey
   - Support multiple POs per requisition

3. **Partial Receives & GRN** (20 hrs)
   - Create GRN model
   - Validate quantities
   - Auto-create stock

### Phase 2 (Weeks 5-8): High Priority
1. **RFQ & Quote System** (20 hrs)
2. **Supplier Performance Tracking** (15 hrs)
3. **Contract Management Integration** (15 hrs)
4. **Payment Integration** (15 hrs)

### Phase 3 (Weeks 9-13): Medium Priority
1. **Approval Rules Engine** (20 hrs)
2. **Three-Way Match** (15 hrs)
3. **Performance Reporting** (10 hrs)

---

## Testing Strategy

### Unit Tests
- PO creation and auto-numbering
- Status validation
- Approval workflow
- Quantity calculations

### Integration Tests
- Complete requisition flow
- Multi-step approval process
- Inventory integration
- Payment matching

### API Tests
- All endpoints
- Approval endpoints
- Reporting endpoints

---

## Conclusion

**Procurement module provides basic PO tracking** with:
- ✓ Purchase order management
- ✓ Requisition system
- ✓ Supplier tracking
- ✓ Basic workflow logic

**But critical issues need fixing**:
- ❌ Workflow not enforced
- ❌ Approval system incomplete
- ❌ PO/Purchase concept confusion
- ❌ Partial receives not integrated
- ❌ No RFQ/quote system
- ❌ Payment integration missing
- ❌ Low test coverage

**Estimated Effort**: 250-350 hours over 3-4 months

