# Finance Module - Comprehensive Audit Documentation

## Executive Summary

The Finance module is the core revenue-tracking system for the ERP, implementing invoice management, payment processing, accounts, budgeting, expenses, and financial reconciliation. It follows Zoho Invoice patterns with comprehensive features for multi-currency support, approval workflows, and payment tracking.

**Module Location**: `finance/`  
**Key Submodules**: invoicing, payment, accounts, budgets, expenses, taxes, reconciliation, analytics  
**Status**: Functional but needs significant enhancements  
**Coverage**: ~40% test coverage, needs expansion to 80%+

---

## Database Schema & Models

### Core Models

#### 1. **Invoice** (finance/invoicing/models.py)
**Extends**: BaseOrder  
**Purpose**: Comprehensive invoice management with Zoho Invoice-like features

**Key Fields**:
```
- invoice_number (CharField, unique, auto-generated)
- invoice_date (DateField, default=timezone.now)
- due_date (DateField)
- status (CharField) - Choices: draft, sent, viewed, partially_paid, paid, overdue, cancelled, void
- payment_terms (CharField) - due_on_receipt, net_15, net_30, net_45, net_60, net_90, custom
- custom_terms_days (IntegerField, nullable)
- sent_at (DateTimeField, nullable)
- viewed_at (DateTimeField, nullable)
- last_reminder_sent (DateTimeField, nullable)
- reminder_count (IntegerField, default=0)
- is_scheduled (BooleanField, default=False)
- scheduled_send_date (DateTimeField, nullable)
- template_name (CharField) - standard, modern, classic, professional
- customer_notes (TextField)
- terms_and_conditions (TextField)
- source_quotation (ForeignKey to Quotation, nullable)
- requires_approval (BooleanField, default=False)
- approval_status (CharField) - not_required, pending, approved, rejected
- approvals (ManyToMany to Approval)
- approved_by (ForeignKey to User, nullable)
- approved_at (DateTimeField, nullable)
- payment_gateway_enabled (BooleanField, default=False)
- payment_gateway_name (CharField)
- payment_link (URLField)
- share_token (CharField, unique, nullable)
- share_url (URLField)
- is_shared (BooleanField, default=False)
- shared_at (DateTimeField, nullable)
- allow_public_payment (BooleanField, default=False)
- is_recurring (BooleanField, default=False)
- recurring_interval (CharField) - monthly, quarterly, yearly
- next_invoice_date (DateField, nullable)
```

**Inherited from BaseOrder**:
- order_number, order_type, source
- customer (ForeignKey to Contact)
- branch (ForeignKey to Branch)
- created_by (ForeignKey to User)
- subtotal, tax_amount, discount_amount, shipping_cost, total
- amount_paid, balance_due, currency, exchange_rate
- items (GenericForeignKey to OrderItem)
- created_at, updated_at

**Key Methods**:
- `generate_invoice_number()` - Auto-generates unique invoice number via DocumentNumberService
- `calculate_due_date()` - Calculates due date based on payment terms
- `mark_as_sent(user)` - Changes status to 'sent'
- `mark_as_viewed()` - Changes status to 'viewed'
- `generate_share_token()` - Creates public sharing token
- `get_public_share_url()` - Returns frontend share URL
- `record_payment(amount, payment_method, reference, payment_date, payment_account)` - Records payment
- `void_invoice(reason)` - Voids invoice
- `clone_invoice()` - Creates copy of invoice
- `send_reminder()` - Sends payment reminder
- `recalculate_payments()` - Ensures payment totals are consistent

**Workflow**:
```
draft → sent → viewed → partially_paid → paid
                    ↘ (if past due) → overdue
                    ↘ (cancel) → cancelled
                    ↘ (void) → void
```

---

#### 2. **DeliveryNote** (finance/invoicing/models.py)
**Extends**: BaseOrder  
**Purpose**: Tracks goods delivery and fulfillment

**Key Fields**:
```
- delivery_note_number (CharField, unique, auto-generated)
- delivery_date (DateField)
- status (CharField) - draft, pending, in_transit, delivered, partially_delivered, cancelled
- source_invoice (ForeignKey to Invoice, nullable)
- source_purchase_order (ForeignKey to PurchaseOrder, nullable)
- driver_name (CharField)
- vehicle_number (CharField)
- received_by (CharField)
- receiver_signature (FileField, nullable)
- notes (TextField)
```

**GAP**: No line-item fulfillment tracking, no way to track partial deliveries per item

---

#### 3. **CreditNote** (finance/invoicing/models.py)
**Extends**: BaseOrder  
**Purpose**: Track refunds/adjustments on invoices

**Key Fields**:
```
- credit_note_number (CharField, unique)
- reference_invoice (ForeignKey to Invoice)
- reference_order (ForeignKey to BaseOrder, nullable)
- reason (TextField)
- adjustment_date (DateField)
- status (CharField) - draft, approved, cancelled
```

---

#### 4. **DebitNote** (finance/invoicing/models.py)
**Extends**: BaseOrder  
**Purpose**: Track additional charges on invoices

**Key Fields**:
```
- debit_note_number (CharField, unique)
- reference_invoice (ForeignKey to Invoice)
- reference_order (ForeignKey to BaseOrder, nullable)
- reason (TextField)
- adjustment_date (DateField)
- status (CharField) - draft, approved, cancelled
```

---

#### 5. **ProformaInvoice** (finance/invoicing/models.py)
**Extends**: BaseOrder  
**Purpose**: Pre-invoice quotations for approval before actual invoicing

**Key Fields**:
```
- proforma_number (CharField, unique)
- proforma_date (DateField)
- conversion_date (DateField, nullable)
- status (CharField) - draft, sent, approved, converted, expired, cancelled
```

---

#### 6. **InvoicePayment** (finance/invoicing/models.py)
**Purpose**: Link invoices with payments (normalized relationship)

**Key Fields**:
```
- invoice (ForeignKey to Invoice)
- payment (ForeignKey to Payment)
- payment_method (CharField)
- reference (CharField)
- payment_date (DateTimeField)
- amount (DecimalField)
- status (CharField) - pending, completed, failed, refunded
```

---

#### 7. **InvoiceEmailLog** (finance/invoicing/models.py)
**Purpose**: Track email sending for Zoho-like functionality

**Key Fields**:
```
- invoice (ForeignKey to Invoice)
- email_type (CharField) - invoice, reminder, payment_received
- recipient_email (EmailField)
- status (CharField) - pending, sent, failed, bounced
- sent_at (DateTimeField, nullable)
- failure_reason (TextField, nullable)
- open_count (IntegerField)
- last_opened_at (DateTimeField, nullable)
- bounce_type (CharField) - soft, hard
```

---

#### 8. **Payment** (finance/payment/models.py)
**Extends**: BaseModel  
**Purpose**: Centralized payment recording system

**Key Fields**:
```
- payment_type (CharField) - invoice_payment, expense_payment, salary_payment, supplier_payment
- amount (DecimalField)
- payment_method (ForeignKey to PaymentMethod)
- reference_number (CharField, unique)
- payment_date (DateTimeField)
- customer (ForeignKey to Contact)
- payment_account (ForeignKey to PaymentAccounts, nullable)
- status (CharField) - pending, completed, failed, refunded, cancelled
- notes (TextField)
- currency (CharField)
- exchange_rate (DecimalField)
```

**Relationships**:
- Links to multiple document types via generic foreign key
- Connected to InvoicePayment, ExpensePayment tables
- Tracks payments across all modules

---

#### 9. **PaymentAccounts** (finance/accounts/models.py)
**Purpose**: Bank and payment account management

**Key Fields**:
```
- business (ForeignKey to Bussiness, nullable)
- name (CharField)
- account_number (CharField, unique)
- account_type (CharField) - bank, cash, credit_card, investment, mobile_money, other
- currency (CharField) - KES, USD, EUR, GBP
- opening_balance (DecimalField)
- balance (DecimalField) - current account balance
- status (CharField) - active, inactive, suspended
- description (TextField, nullable)
- bank_name (CharField, nullable)
- branch (CharField, nullable)
- swift_code (CharField, nullable)
- iban (CharField, nullable)
- created_at (DateTimeField)
- updated_at (DateTimeField)
```

**Key Methods**:
- Account balance tracking
- Multi-currency support
- Account status management

---

#### 10. **Budget** (finance/budgets/models.py)
**Purpose**: Budget planning and tracking

**Key Fields**:
```
- name (CharField)
- start_date (DateField)
- end_date (DateField)
- status (CharField) - draft, approved, rejected, archived
- created_by (ForeignKey to CustomUser)
- created_at (DateTimeField)
- updated_at (DateTimeField)
```

**Relationships**:
- Has many BudgetLine items
- Tracks categorized budget allocations

---

#### 11. **BudgetLine** (finance/budgets/models.py)
**Purpose**: Individual budget line items

**Key Fields**:
```
- budget (ForeignKey to Budget)
- category (CharField) - revenue, expense, capex, other
- name (CharField)
- amount (DecimalField)
- notes (CharField, nullable)
```

---

#### 12. **Expense** (finance/expenses/models.py)
**Purpose**: Track business expenses with recurring support

**Key Fields**:
```
- register (ForeignKey to Register, nullable)
- branch (ForeignKey to Branch)
- category (ForeignKey to ExpenseCategory)
- reference_no (CharField)
- date_added (DateField)
- expense_for_user (ForeignKey to User, nullable)
- expense_for_contact (ForeignKey to Contact, nullable)
- attach_document (FileField, nullable)
- applicable_tax (ForeignKey to Tax, nullable)
- currency (CharField, default='KES')
- exchange_rate (DecimalField)
- total_amount (DecimalField)
- expense_note (TextField, nullable)
- is_refund (BooleanField)
- is_recurring (BooleanField)
- interval_type (CharField) - Daily, Weekly, Monthly, Yearly
- recurring_interval (PositiveIntegerField)
- repetitions (IntegerField)
```

**Key Relationships**:
- Links to ExpensePayment table
- Tracks single and recurring expenses

---

#### 13. **Tax & TaxGroup** (finance/taxes/models.py)
**Purpose**: Tax configuration and management

**Key Fields** (Tax):
```
- name (CharField)
- percentage (DecimalField)
- account (ForeignKey to PaymentAccounts, nullable)
- description (TextField, nullable)
- is_active (BooleanField)
- tax_type (CharField) - sales, purchase, other
```

**TaxGroup**:
```
- name (CharField)
- taxes (ManyToMany to Tax)
- is_active (BooleanField)
```

---

## Serializers & API Layer

### 1. **InvoiceSerializer** (finance/invoicing/serializers.py)
**Extends**: BaseOrderSerializer  
**Used for**: Detailed invoice retrieve/list operations

**Key Fields**:
- All Invoice model fields
- customer_details (nested ContactSerializer)
- items (nested OrderItemSerializer)
- balance_due_display (computed)
- is_overdue (computed)
- days_until_due (computed)
- status_display (readable choice)
- payment_terms_display (readable choice)
- current_approver_id (from approval workflow)
- pending_approvals (from approval workflow)

**Read-only Fields**: invoice_number, order_number, sent_at, viewed_at, approved_by, approved_at, balance_due

---

### 2. **InvoiceFrontendSerializer**
**Used for**: Frontend list/detail views with optimized performance

**Compact structure** - includes only essential fields for UI display

---

### 3. **InvoiceCreateSerializer**
**Used for**: Creating and updating invoices

**Includes**:
- InvoiceItemCreateSerializer (write-only) for line items
- Handles nested item creation in single request

---

### 4. **InvoicePaymentSerializer**
**Fields**:
- invoice_number (related)
- payment_account_name (related)
- All payment details

---

### 5. **PurchaseOrderSerializer** (procurement/orders/serializers.py)
**Extends**: BaseOrderSerializer  
**Key additions**:
- supplier_name (computed)
- requisition_reference (related)
- approvals (nested ApprovalSerializer)
- total_paid (computed from po_payments)
- current_approver_id, pending_approvals_list

---

## ViewSets & API Endpoints

### 1. **InvoiceViewSet** (finance/invoicing/views.py)
**Base Class**: BaseModelViewSet  
**Authentication**: IsAuthenticated  
**Filtering**: DjangoFilterBackend  
**Search Fields**: invoice_number, customer first_name, last_name, business_name

**Key Custom Actions**:
- `@action(detail=True, methods=['post']) mark_sent(request)`
- `@action(detail=True, methods=['post']) schedule_send(request)`
- `@action(detail=True, methods=['post']) record_payment(request)`
- `@action(detail=True, methods=['post']) void_invoice(request)`
- `@action(detail=True, methods=['get']) download_pdf(request)`
- `@action(detail=True, methods=['post']) send_reminder(request)`
- `@action(detail=True, methods=['get']) payment_history(request)`

**Query Optimization**:
```python
queryset = Invoice.objects.select_related(
    'customer__user',
    'branch',
    'approved_by',
    'source_quotation',
).prefetch_related(
    'items__content_type',
    'payments',
)
```

**Performance Issues**:
- ❌ Missing prefetch_related for approvals
- ❌ N+1 issue possible with payment gateway lookups
- ❌ Missing select_related for created_by

---

### 2. **PaymentViewSet** (finance/payment/views.py)
**Key Actions**:
- Create, retrieve, update, delete payments
- Record payment outcomes
- Handle refunds
- Track payment status

---

### 3. **PaymentAccountsViewSet** (finance/accounts/views.py)
**Key Functionality**:
- Account CRUD operations
- Balance tracking
- Account status management
- Multi-currency support

---

### 4. **TaxViewSet** (finance/taxes/views.py)
**Key Functionality**:
- Tax rate management
- Tax group management
- Tax category management
- Tax period tracking

---

## Database Relationships & Data Flow

### Invoice Workflow
```
1. Create Invoice (draft)
   ├─ Set customer, items, payment terms
   ├─ Auto-generate invoice_number
   ├─ Calculate due_date

2. Send Invoice (sent)
   ├─ Update sent_at
   ├─ Create InvoiceEmailLog
   ├─ Update status

3. Customer Views (viewed)
   ├─ Update viewed_at
   ├─ Track via email logs

4. Record Payment (partially_paid → paid)
   ├─ Create Payment record
   ├─ Create InvoicePayment link
   ├─ Update amount_paid
   ├─ Recalculate balance_due

5. Handle Overdue (overdue)
   ├─ Auto-update if past due_date
   ├─ Send reminders

6. Final States
   ├─ paid (amount_paid >= total)
   ├─ cancelled
   ├─ void
```

### Payment Flow
```
Payment Created
├─ Link to Invoice (via InvoicePayment)
├─ Link to PaymentAccount
├─ Record Payment Method
├─ Set Currency/Exchange Rate
├─ Update Invoice amount_paid
└─ Recalculate Invoice balance_due
```

### Tax & Expense Flow
```
Expense Creation
├─ Select Category
├─ Apply Tax (optional)
├─ Set Branch
├─ Can be recurring
├─ Link to ExpensePayment
└─ Link to PaymentAccount
```

---

## URL Configuration

**Finance Module URLs** (finance/urls.py):
```
POST/GET   /api/invoices/                          - List/Create invoices
GET        /api/invoices/{id}/                     - Retrieve invoice
PUT/PATCH  /api/invoices/{id}/                     - Update invoice
DELETE     /api/invoices/{id}/                     - Delete invoice
POST       /api/invoices/{id}/mark_sent/           - Mark as sent
POST       /api/invoices/{id}/schedule_send/       - Schedule sending
POST       /api/invoices/{id}/record_payment/      - Record payment
POST       /api/invoices/{id}/void_invoice/        - Void invoice
GET        /api/invoices/{id}/download_pdf/        - Download PDF
POST       /api/invoices/{id}/send_reminder/       - Send reminder
GET        /api/invoices/{id}/payment_history/     - View payments

GET/POST   /api/payments/                          - List/Create payments
GET        /api/payments/{id}/                     - Retrieve payment

GET/POST   /api/payment-accounts/                  - List/Create accounts
GET        /api/payment-accounts/{id}/             - Retrieve account

GET/POST   /api/taxes/                             - List/Create taxes
GET/POST   /api/expenses/                          - List/Create expenses

GET/POST   /api/budgets/                           - List/Create budgets
GET/POST   /api/budgets/{id}/lines/                - Manage budget lines
```

---

## Critical Gaps & Issues

### 1. **Invoice-Delivery Note Integration** (CRITICAL - 20-30 hrs)
**Current State**:
- DeliveryNote exists but not linked to invoice fulfillment
- No line-item level fulfillment tracking
- Can't mark partial deliveries per item

**Impact**:
- ❌ Can't track which invoice items are fulfilled
- ❌ No visibility into pending fulfillment
- ❌ Shipping documents don't link to invoice items

**Solution**:
- Add DeliveryLineItem model linking to OrderItem
- Track fulfillment_status per line item
- Add fulfillment_summary to InvoiceSerializer
- Create delivery note endpoints with item-level tracking

### 2. **Payment Processing Gaps** (HIGH - 15-20 hrs)
**Current State**:
- Basic payment recording exists
- No duplicate payment prevention
- No overpayment validation
- Payment reconciliation incomplete

**Issues**:
- ❌ Can't prevent recording same payment twice
- ❌ Can record payments exceeding invoice total
- ❌ No payment matching/reconciliation
- ❌ Missing payment reversal/adjustment logic

**Solution**:
- Add unique constraint on payment reference
- Add validation: amount <= balance_due
- Implement payment matching algorithm
- Create payment adjustment operations

### 3. **Email/Notification System** (HIGH - 15-20 hrs)
**Current State**:
- InvoiceEmailLog table exists but incomplete
- Email tracking not connected to actual sending
- No bounce handling
- No retry logic

**Issues**:
- ❌ Email logs created but not used for actual sending
- ❌ No integration with email service
- ❌ Missing bounce/failure handling
- ❌ No scheduled email implementation

**Solution**:
- Integrate with SendGrid/Mailgun
- Implement actual email sending on mark_sent
- Add bounce handling and quarantine
- Implement scheduled send via Celery

### 4. **PDF Generation** (HIGH - 15-20 hrs)
**Current State**:
- Basic PDF generation exists (ReportLab)
- Incomplete template system
- No signature/receipt placeholders

**Issues**:
- ❌ Limited template options
- ❌ No delivery confirmation integration
- ❌ Missing QR code for payment
- ❌ No custom branding support

**Solution**:
- Implement full template engine
- Add QR code to payment link
- Create signature capture on delivery
- Support custom logos/branding

### 5. **Approval Workflow** (HIGH - 20-25 hrs)
**Current State**:
- Approval fields exist in Invoice model
- Not enforced as workflow
- No routing logic

**Issues**:
- ❌ Approval is optional, not enforced
- ❌ No approval chain/routing
- ❌ No rejection handling
- ❌ No escalation logic

**Solution**:
- Create formal approval workflow state machine
- Implement approval routing rules
- Add rejection with reasons
- Implement escalation to supervisors

### 6. **Recurring Invoices** (MEDIUM - 20-25 hrs)
**Current State**:
- Model fields exist (is_recurring, recurring_interval)
- Not implemented in business logic
- No auto-generation

**Issues**:
- ❌ Can't automatically generate recurring invoices
- ❌ No interval tracking
- ❌ No notification system
- ❌ Can't pause/cancel recurrence

**Solution**:
- Create Celery task to generate recurring invoices
- Add end_date and pause options
- Create recurring invoice status tracking
- Add notification before auto-generation

### 7. **Foreign Key Integrity** (MEDIUM - 10-15 hrs)
**Issues**:
- ❌ Invoice.customer required but nullable in some queries
- ❌ Branch not always set causing document generation failures
- ❌ source_quotation can be deleted orphaning invoices

**Solution**:
- Make required fields non-nullable
- Add CASCADE/PROTECT constraints
- Add data validation on save

### 8. **Test Coverage Gaps** (CRITICAL - 80-120 hrs)
**Current State**:
- Tests exist but minimal (~30% coverage)
- Missing edge case testing
- No integration test coverage

**Critical Tests Needed**:
- Invoice creation flow (10 hrs)
- Payment recording and balance calculation (15 hrs)
- Status transitions and validation (15 hrs)
- Email log tracking (10 hrs)
- PDF generation (15 hrs)
- Approval workflow (20 hrs)
- Integration with other modules (30 hrs)

### 9. **Currency & Exchange Rate** (MEDIUM - 15-20 hrs)
**Current State**:
- Fields exist but not enforced
- No exchange rate history
- No rate validation

**Issues**:
- ❌ Can't audit exchange rates used
- ❌ No historical rate tracking
- ❌ Manual rate entry prone to errors

**Solution**:
- Add ExchangeRate historical model
- Integrate with currency API
- Add rate validation and audit trail

### 10. **Error Handling Standardization** (CRITICAL - 15-20 hrs)
**Current State**:
- Mixed error responses (ValidationError, DRF Serializer errors, plain text)
- No consistent error codes
- Poor error messages

**Solution**:
- Create unified error response format
- Add error codes for all scenarios
- Improve error messages with resolution steps

---

## Performance Optimization Opportunities

### 1. **Query Optimization** (5-10 hrs)
```python
# Current InvoiceViewSet
queryset = Invoice.objects.select_related(
    'customer__user',
    'branch',
    'approved_by',
    'source_quotation',
).prefetch_related(
    'items__content_type',
    'payments',
)

# Missing optimizations:
# - Need: .prefetch_related('approvals__approver')
# - Need: .select_related('created_by')
# - Need: .prefetch_related('invoice_email_logs')
```

### 2. **Caching Strategy** (10-15 hrs)
- Cache invoice PDF generation results
- Cache tax rates
- Cache account balances
- Implement cache invalidation on updates

### 3. **Database Indexes** (5 hrs)
- Add index on (customer, status)
- Add index on (branch, invoice_date)
- Add index on (payment_status)

---

## Security Gaps

### 1. **Invoice Sharing** (5-10 hrs)
- ✓ Share token implemented
- ❌ No rate limiting on public endpoints
- ❌ No expiration on share tokens
- ❌ No download tracking

### 2. **Payment Security** (20-30 hrs)
- ❌ No PCI DSS compliance framework
- ❌ No payment method encryption
- ❌ No fraud detection
- ❌ No 3D Secure integration

### 3. **Access Control** (10-15 hrs)
- ❌ Can users access competitors' invoices?
- ❌ No row-level security
- ❌ No audit trail of document access

---

## Recommended Implementation Roadmap

### Phase 1 (Weeks 1-4): Critical Fixes
1. **Delivery Note Integration** - Add fulfillment tracking (20 hrs)
2. **Payment Validation** - Prevent duplicate/overpayment (15 hrs)
3. **Test Expansion** - Core invoice tests (40 hrs)

### Phase 2 (Weeks 5-8): High Priority Features
1. **Email Integration** - Connect to SendGrid (15 hrs)
2. **Approval Workflow** - Formal state machine (20 hrs)
3. **PDF Enhancement** - Full templating (15 hrs)
4. **Query Optimization** - Performance improvements (10 hrs)

### Phase 3 (Weeks 9-13): Medium Priority
1. **Recurring Invoices** - Auto-generation (20 hrs)
2. **Currency Exchange** - Rate tracking (15 hrs)
3. **Error Standardization** - Unified responses (15 hrs)
4. **Caching** - Performance (10 hrs)

### Phase 4+ : Long-term
1. Payment gateway integration
2. Advanced analytical functionality
3. Custom reporting
4. Audit trail completeness

---

## Testing Strategy

### Unit Tests Needed
- Invoice creation and auto-numbering
- Due date calculation from payment terms
- Status transitions and validation
- Balance calculation (total - amount_paid = balance_due)
- Payment recording and reversal
- Tax calculation
- Email log operations
- Approval state transitions

### Integration Tests Needed
- Complete invoice workflow (create → send → pay → reconcile)
- Multi-currency payment processing
- Recurring invoice generation
- Integration with Quotation module
- Integration with DeliveryNote module

### API Tests Needed
- All endpoints with valid/invalid data
- Authentication and authorization
- Pagination, filtering, searching
- PDF download and generation
- Email sending simulation
- Payment recording with validation

---

## Conclusion

**The Finance module provides a solid foundation** with:
- ✓ Comprehensive invoice management
- ✓ Multi-currency support
- ✓ Payment tracking
- ✓ Tax and expense management
- ✓ Basic approval workflow

**But needs critical improvements**:
- ❌ Invoice-DeliveryNote integration
- ❌ Robust payment validation
- ❌ Email and PDF systems connection
- ❌ Formal approval workflows
- ❌ Comprehensive test coverage
- ❌ Error handling standardization

**Estimated Total Effort**: 350-450 hours over 3-4 months

