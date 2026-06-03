# ERP Decomposition — Feature-Gap Analysis (per torn-down domain)

Generated during the ERP → microservices decomposition (2026-06). For each domain
removed from the ERP, this records **what the ERP had**, the **owner service** it moved
to, the **integration** the ERP now uses, and **known gaps** in the owner service that
still need closing for full parity. Pre-removal code is preserved on
`backup/pre-decomposition-20260603` (erp-api + erp-ui) for reference.

Legend: ✅ verified this cycle · ⚠️ partial / known gap · ❓ owner not audited this cycle (needs parity audit).

---

## 1. Products + Stock + Procurement + Manufacturing + Asset register → inventory-api

**ERP had:** `ecommerce.product` (item/category/variant), `ecommerce.stockinventory`
(stock, units, warehouses, transfers, adjustments, lots, warranties), `ecommerce.vendor`
(suppliers), `procurement.*` (purchases, requisitions, orders, supplier_performance,
contracts), `manufacturing` (formulas/BOM, batches, QC, analytics), `assets/*`
(register, maintenance, transfers, disposal, insurance, audit).

**Owner / integration:** inventory-api (S2S + NATS events; PO PDF via documents module).

**Status & gaps:**
- ✅ Procurement: requisitions, contracts, purchase-returns, supplier-performance,
  service-delivery, procurement analytics implemented; stock effects wired.
- ✅ Manufacturing: production-batch lifecycle + QC + raw-material consumption /
  finished-goods restock; analytics.
- ✅ Asset register: assets + categories + maintenance/transfer/disposal/insurance/
  audit/reservation; emits `inventory.asset.depreciation_due`.
- ✅ Documents: tenant-branded premium PO PDF (fpdf renderer) + DocumentSequence.
- ✅ inventory-ui: requisitions, production-batches, fixed-assets pages.
- ⚠️ **GRN + 3-way match (PO ↔ GRN ↔ invoice) and RFQ/tender** not yet implemented — table-stakes procurement gap.
- ⚠️ Domain RBAC: procurement/manufacturing/asset endpoints reuse `inventory.items.*` /
  `inventory.purchases.*` permissions rather than dedicated permission strings.
- ⚠️ Tests + OpenAPI: extras endpoints now annotated (swagger regenerated); unit/integration tests still thin.

## 2. Finance + Payments + Tax/eTIMS + Asset depreciation → treasury-api

**ERP had:** `finance.accounts` (GL/CoA), `finance.invoicing`, `finance.quotations`,
`finance.payment`, `finance.expenses`, `finance.budgets`, `finance.cashflow`,
`finance.reconciliation`, `finance.taxes`; `integrations.payments.*` (mpesa/paystack/
paypal/card), KRA/eTIMS, bank & government service config; asset depreciation schedule.

**Owner / integration:** treasury-api (mature). ERP payroll posts journals via
`erp.payroll.processed`; ERP retains only generic FX fetch (ExchangeRateAPISettings →
core.ExchangeRate) + outbox.

**Status & gaps:**
- ✅ Treasury already owns GL, AR/AP, payments, tax/eTIMS, budgets, reconciliation, equity.
- ✅ Fixed-asset depreciation: `FixedAssetDepreciation` schema + subscriber on
  `inventory.asset.depreciation_due` + balanced GL posting (DR 6500 / CR 1700).
- ⚠️ **GL accounts 6500 (Depreciation Expense) / 1700 (Accumulated Depreciation) are
  not in the default tenant CoA seed** — depreciation record is created but the GL
  entry is skipped until those accounts exist. Seed them per tenant.
- ⚠️ Payroll→treasury journal posting (`erp.payroll.processed`) consumer: confirm treasury subscribes.

## 3. CRM (contacts / leads / pipeline / campaigns) → marketflow ❓

**ERP had:** `crm.contacts` (Contact = customer master), `crm.leads`, `crm.pipeline`
(deals), `crm.campaigns`; ERP `CustomerGroup`.

**Owner / integration:** marketflow (customer master). Other services hold `crm_contact_id`.
ERP walk-in Contact creation removed (marketflow owns it via user-provisioning event).

**Status & gaps:**
- ❓ marketflow CRM parity **not audited this cycle** — verify Contact/Account, leads,
  pipeline/deals, campaigns exist with equivalent fields; map ERP `CustomerGroup` →
  marketflow Account/segment. Multi-touch attribution = documented differentiator backlog.

## 4. Cart + Online orders → ordering-backend ❓ · 5. POS → pos-api ❓

**ERP had:** `ecommerce.cart`, `ecommerce.order` (online orders), `ecommerce.pos`
(registers/sales/returns), `core_orders.BaseOrder` (retired).

**Owner / integration:** ordering-backend (carts + online orders); pos-api (POS).

**Status & gaps:**
- ❓ ordering-backend & pos-api parity **not audited this cycle**. Verify storefront
  cart/checkout, order lifecycle, delivery refs (ordering) and registers/sales/returns/
  suspended-sales (pos). POS clock-in bridge (was `integrations.pos_bridge_views`) →
  re-home as a pos-api↔ERP-HR S2S call if still needed for attendance.

## 6. Notifications → notifications-api

**ERP had:** `notifications` (templates, delivery, providers, preferences, bounce,
email/SMS/push services). KEEP apps (HR/payroll, auth, core) called `EmailService` /
`NotificationService` directly.

**Owner / integration:** notifications-api. ERP now emits to the outbox via
`integrations.notifications_client` (drop-in EmailService/NotificationService):
- `erp.email.requested` — {subject, message, recipient_list, html_message, cc, bcc, attachments[]}
- `erp.notification.requested` — {user_id, email, title, message, type, channels, data, action_url, templates, context}

**Status & gaps:**
- ⚠️ **notifications-api must add consumers** for `erp.email.requested` /
  `erp.notification.requested` (subjects above) — verify/implement.
- ⚠️ **Email attachments** (e.g. payroll payslip PDFs) are base64-embedded in the event
  payload by the client; confirm notifications-api handles attachment payloads, or
  switch payslip delivery to an S2S multipart endpoint for large files.
- ⚠️ In-app notification bell in erp-ui kept (generic endpoint) — confirm it points at notifications-api.

---

## ERP retained (HR + internal-ops) — no gaps, kept intact
`hrm.*` (employees, payroll, payroll_settings, attendance, leave, recruitment,
performance, appraisals, training), `approvals` (generic/non-financial), `core`,
`business`, `addresses` (HR address fields), `task_management`, `error_handling`,
`caching`, `integrations` (outbox + FX + S2S), `authmanagement` (SSO client + thin
CustomUser shadow).

## Cross-cutting follow-ups
- core executive/shared analytics: cross-domain figures now return 0 (owner data gone) —
  migrate cross-domain BI to Superset; reduce the ERP executive dashboard to HR/ops.
- Orphaned tables: removed-domain tables remain in any pre-existing ERP DB (Django does
  not drop tables for uninstalled apps). Drop manually after data migration to owners.
