# ERP Module Removal Plan

**Created:** April 2026
**Status:** Planning — deletion deferred until all owner microservices are production-ready
**Scope:** Remove ~85+ models across ~16 Django apps that are now owned by dedicated microservices

---

## Guiding Principles

1. **No code deletion until the owner microservice is production-ready** for that domain.
2. Each module below has a designated **owner microservice** — that service is the single source of truth.
3. Before deletion, any **unique logic** in the ERP module that does not yet exist in the owner must be migrated first.
4. Modules marked **KEEP** remain in ERP and follow a **zero-duplication integration pattern**: they reference external entities by ID only (e.g. `payment_intent_id`, `inventory_item_id`) and call owner APIs or consume events. No local copies of owned data.
5. Deletion proceeds in **phases 1-5**, ordered by dependency and microservice readiness.

---

## Modules to KEEP in ERP

These modules remain in erp-api. They integrate with microservices via reference IDs, REST, and NATS events only.

| Module | Description | Integration Notes |
|--------|-------------|-------------------|
| **HRM** | Employees, payroll, attendance, leave, performance, recruitment, training | Publishes `erp.payroll.processed`, `erp.leave.requested`; references treasury-api for payment processing |
| **CRM** | Leads, opportunities, customers, campaigns | Publishes `erp.opportunity.won`; references treasury-api for invoices |
| **Procurement** | Purchase orders, suppliers, RFQs | Publishes `erp.purchase_order.created/received`; references inventory-api for stock receipt |
| **Manufacturing** | Work orders, BOM, production planning, quality control | Publishes `erp.work_order.started/completed`; references inventory-api for material consumption and finished goods |
| **Assets** | Asset lifecycle, depreciation, disposal | References treasury-api Transaction model for depreciation entries |
| **Approvals** | Generic approval workflow engine | Used by HRM (leave, payroll), Procurement (PO), Manufacturing (work orders) |
| **Core** | Shared models, base classes, utilities, exceptions | Foundation for all kept modules |
| **Addresses** | Address management (shared across modules) | Referenced by HRM, CRM, Procurement |
| **Task Management** | Internal task tracking | Used by HRM, Manufacturing |
| **Error Handling** | Custom exceptions, error codes | Foundation for all kept modules |

### Zero-Duplication Integration Pattern (Kept Modules)

```
Kept ERP Module                  Owner Microservice
─────────────────                ──────────────────
HRM payroll.processed ──event──> treasury-api (create payment journal)
CRM opportunity.won   ──event──> treasury-api (create invoice)
Procurement PO.received ─event─> inventory-api (stock receipt)
                                 treasury-api (create vendor bill)
Manufacturing work_order ─event> inventory-api (consume materials, receive finished goods)

All modules: store only reference IDs (payment_intent_id, inventory_item_id, etc.)
All modules: call owner REST APIs for reads; never store copies of owned entities
```

---

## Modules Marked for Deletion

### Phase 1: E-commerce / POS (Owner: pos-api, ordering-backend)

These modules duplicate functionality now owned by pos-api and ordering-backend.

| Django App / Module | Models (approx.) | Owner Microservice | Unique Logic to Migrate First | Status |
|---------------------|-------------------|--------------------|-------------------------------|--------|
| `ecommerce/pos/` | POSOrder, POSOrderLine, POSSession, CashDrawer, Tender, DailyClosing, ShiftSummary | **pos-api** | Daily closing reconciliation report; receipt PDF generation logic | Pending |
| `ecommerce/order/` | Order, OrderItem, OrderStatus, OrderHistory, ReturnRequest, ReturnLine | **ordering-backend** | Return/RMA request workflow (ReturnRequest, ReturnLine schemas + handlers) | Pending |
| `ecommerce/product/` | Product, ProductVariant, ProductCategory, ProductImage, ProductAttribute, PriceList, PriceTier | **inventory-api** | Bulk/quantity pricing tiers; product attribute matrix | Pending |
| `ecommerce/stockinventory/` | StockItem, StockMovement, StockAdjustment, WarehouseLocation, StockAlert, LowStockRule | **inventory-api** | Sub-warehouse locations (bin/shelf/aisle); low-stock alert rules; stock alert event publishing | Pending |
| `ecommerce/cart/` | Cart, CartItem, CartSession | **ordering-backend** | None (fully replicated in ordering-backend) | Pending |
| `ecommerce/vendor/` | Vendor, VendorProduct, VendorRating, VendorPayout | **inventory-api** (Supplier) + **treasury-api** (payouts) | Vendor rating system (deferred) | Pending |
| `ecommerce/analytics/` | SalesAnalytics, ProductPerformance, CustomerCohort, RFMSegment, ConversionFunnel | **Superset** (deferred) | Cohort analysis, RFM segmentation — migrate to Superset dashboards | Pending |

### Phase 2: Finance (Owner: treasury-api)

All finance modules are now owned by treasury-api.

| Django App / Module | Models (approx.) | Owner Microservice | Unique Logic to Migrate First | Status |
|---------------------|-------------------|--------------------|-------------------------------|--------|
| `finance/accounts/` | ChartOfAccounts, Account, JournalEntry, JournalLine, Transaction, Ledger, AccountingPeriod | **treasury-api** | Double-entry journal posting logic; period close procedures | Pending |
| `finance/invoicing/` | Invoice, InvoiceLine, CreditNote, DebitNote, RecurringInvoice | **treasury-api** | Recurring invoice scheduler; credit/debit note workflows | Pending |
| `finance/billing/` | Bill, BillLine, VendorBill, VendorBillLine, BillPayment | **treasury-api** | Vendor bill matching to PO; partial payment allocation | Pending |
| `finance/tax/` | TaxCode, TaxRate, TaxPeriod, TaxFiling, TaxReturn, WithholdingTax | **treasury-api** | Kenyan tax computation (PAYE, VAT, WHT); KRA iTax filing | Pending |
| `finance/etims/` | eTIMSDevice, eTIMSInvoice, eTIMSTransmission, eTIMSConfig | **treasury-api** | eTIMS device registration; invoice transmission to KRA | Pending |
| `finance/banking/` | BankAccount, BankStatement, BankStatementLine, BankReconciliation, ReconciliationRule | **treasury-api** | Bank statement import/parsing; auto-reconciliation rules | Pending |
| `finance/budgeting/` | Budget, BudgetLine, BudgetPeriod, BudgetVariance | **treasury-api** | Budget vs actual variance analysis | Pending |
| `finance/expenses/` | Expense, ExpenseCategory, ExpenseClaim, ExpenseApproval | **treasury-api** | Expense claim approval workflow tied to ERP Approvals module | Pending |
| `finance/quotations/` | Quotation, QuotationLine, QuotationRevision | **treasury-api** | Quotation-to-invoice conversion | Pending |
| `finance/forecasting/` | Forecast, ForecastDataPoint, ForecastModel | **treasury-api** | Cash flow forecasting algorithms | Pending |
| `finance/equity/` | EquityTransaction, DividendDeclaration, ShareholderReport | **treasury-api** | Dividend calculation logic | Pending |
| `finance/reporting/` | FinancialReport, TrialBalance, ProfitAndLoss, BalanceSheet, CashFlowStatement | **treasury-api** + **Superset** | Polars-based report generation (migrate formulas to treasury-api) | Pending |

### Phase 3: Payments & Integrations (Owner: treasury-api, notifications-api)

| Django App / Module | Models (approx.) | Owner Microservice | Unique Logic to Migrate First | Status |
|---------------------|-------------------|--------------------|-------------------------------|--------|
| `integrations/payments/mpesa/` | MpesaTransaction, MpesaCallback, MpesaConfig, STKPush | **treasury-api** | M-Pesa STK push flow; callback handling; B2C/B2B flows | Pending |
| `integrations/payments/stripe/` | StripePayment, StripeWebhook, StripeConfig | **treasury-api** | Stripe webhook signature verification | Pending |
| `integrations/payments/paypal/` | PayPalPayment, PayPalConfig | **treasury-api** | PayPal IPN/webhook handling | Pending |
| `integrations/payments/bank_transfer/` | BankTransferPayment, BankTransferConfig | **treasury-api** | Bank transfer matching logic | Pending |

### Phase 4: Notifications (Owner: notifications-api)

| Django App / Module | Models (approx.) | Owner Microservice | Unique Logic to Migrate First | Status |
|---------------------|-------------------|--------------------|-------------------------------|--------|
| `notifications/email/` | EmailTemplate, EmailLog, EmailConfig | **notifications-api** | Email template HTML/content; Celery send tasks | Pending |
| `notifications/sms/` | SMSTemplate, SMSLog, SMSProvider, SMSConfig | **notifications-api** | SMS provider abstraction (AfricasTalking, Twilio); send logic | Pending |
| `notifications/push/` | PushTemplate, PushSubscription, PushLog | **notifications-api** | FCM/APNs push notification logic | Pending |
| `notifications/in_app/` | InAppNotification, NotificationPreference | **notifications-api** | User preference management | Pending |

### Phase 5: E-commerce Orders (Owner: ordering-backend)

| Django App / Module | Models (approx.) | Owner Microservice | Unique Logic to Migrate First | Status |
|---------------------|-------------------|--------------------|-------------------------------|--------|
| `core_orders/` | CoreOrder, CoreOrderLine, OrderFulfillment, ShippingLabel, TrackingEvent | **ordering-backend** + **logistics-api** | Order fulfillment state machine; shipping label generation | Pending |

---

## Deletion Procedure (Per Phase)

1. **Audit**: Identify all unique business logic in the ERP module not yet in the owner microservice.
2. **Migrate Logic**: Port any unique logic to the owner microservice. Open PRs, get tests passing.
3. **Integration Verification**: Confirm the kept ERP modules can call the owner microservice for all use cases previously handled locally.
4. **Feature Flag**: Add a feature flag to disable the ERP module's endpoints (keep code, disable routes).
5. **Soak Period**: Run with the flag off for 2 weeks in production, monitoring for regressions.
6. **Delete**: Remove Django app, models, migrations, views, serializers, URLs, and tests.
7. **Database Cleanup**: Drop tables via Django migration (reversible) or raw SQL after backup.

---

## Summary

| Phase | Apps | Approx. Models | Owner(s) | Blocked By |
|-------|------|----------------|----------|------------|
| 1 | ecommerce/* (7 apps) | ~30 | pos-api, ordering-backend, inventory-api | POS returns, ordering RMA, inventory pricing tiers |
| 2 | finance/* (12 apps) | ~40 | treasury-api | Treasury quotation/expense/tax/banking features |
| 3 | integrations/payments/* (4 apps) | ~10 | treasury-api | Treasury payment gateway integrations |
| 4 | notifications/* (4 apps) | ~8 | notifications-api | Notification template migration |
| 5 | core_orders/ (1 app) | ~5 | ordering-backend, logistics-api | Fulfillment state machine in ordering-backend |
| **Total** | **~28 apps** | **~93 models** | | |

---

## References

- [Architecture Overview](./architecture-overview.md)
- [Integrations Guide](./integrations.md)
- [Cross-Service Data Ownership](../../../shared-docs/CROSS-SERVICE-DATA-OWNERSHIP.md)
