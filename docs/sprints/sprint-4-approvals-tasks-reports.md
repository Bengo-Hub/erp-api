# Sprint 4 — Approvals, Tasks, Reports, Business/Core/Addresses config, Events polish

> The cross-cutting engines and configuration that the HR modules lean on, plus building the
> `reports` module that is effectively un-built in Django. References: `approvals/`, `erd.md §10`,
> `task_management/`, `hrm/payroll/services/reports_service.py`, `p10a_formatter.py`, `business/`,
> `core/`, `addresses/`, `integrations/{branding,taxes,tasks,notifications_client}.py`.

## Goals
- A typed, tenant-scoped approval-matrix engine reused by leave/payroll/contract/appraisal.
- Real reporting (P9/P10A/statutory/bank/muster/variance).
- Slim per-tenant business/core/address config; FX cron; branding read-through; event hardening.

## Scope

### `modules/approvals`  (reuse inventory-api Ent `ApprovalRule/Request/Step/Action`)
- Replace Django **GenericForeignKey** (`content_type_id`+`object_id`) with a typed
  `module` enum (`payroll|leave_request|contract|appraisal|performance_review|recruitment_offer|general`)
  + UUID `object_id` (fixes `gaps-and-bugs.md §4`).
- **Drop decomposed workflow types** (`purchase_order|expense|invoice|requisition`) — fixes §4.
- `ApprovalWorkflow`/`Step` become **tenant-scoped** (currently global — fixes §4); steps support
  `user|role|department_head|manager|owner` approver resolution **without** the broken
  `from hrm.models import Employee` import (fixes §8 / `approvals/models.py:118,149`).
- Multi-step, threshold auto-approve, delegation; emit approval events/notifications.

### `modules/tasks`  (replace Celery task tracker)
- `Task`(+`TaskLog`), `TaskTemplate` as Go job records; execution via worker goroutines / NATS;
  progress via SSE or polling (replace Channels consumers). Tenant-scoped.

### `modules/reports`  (**build for real** — Django `reports/` is empty)
- Port `reports_service.py` + `p10a_formatter.py`: **P9**, **P10A**, statutory deductions,
  bank net-pay schedule, muster roll, withholding-tax, payroll variance.
- Export to CSV/XLSX/PDF (reportlab → a Go PDF lib); tenant + period + outlet/department filters.
- Use branding from `platform/auth` read-through cache for PDF headers (logo/colors/KRA PIN/address).

### `modules/business` + `modules/core` + `modules/addresses`
- `business`: `Business` (rename from misspelled `Bussiness`; fix `finacial_year_start_month` typo),
  `Branch`, `BrandingSettings` (cache only — auth-api is SoT), `TaxRates` (display cache),
  `PrefixSettings`, `DocumentSequence` (port the SELECT-FOR-UPDATE locking → inventory-api
  `documentsequence` pattern), `ServiceTypes`, `PickupStations`. Per-tenant; `public-branding` endpoint.
- `core`: reference data (`Region`, `Department`, `Project`(+category), `BankInstitution`/`BankBranch`),
  `ExchangeRate`, per-tenant `RegionalSettings`/`AppSettings`. **Do NOT port** the executive dashboard
  that imports decomposed `finance.*`/`crm.*`/`ecommerce.*` (fixes §5); if a cross-domain dashboard is
  needed, aggregate via S2S to owner services.
- `addresses`: `AddressBook`, `DeliveryRegion`, `AddressValidation` (CRUD, tenant/user-scoped).

### Integrations polish (`platform/*`)
- **FX cron** (port `integrations/tasks.fetch_exchange_rates` Celery Beat → cron goroutine / CronJob)
  writing `ExchangeRate` rows; `ExchangeRateAPISettings` with the provider key **re-keyed into the
  secret store** (not DB Fernet — fixes §1.1/§1.2).
- **Branding/taxes read-through** caches (`platform/auth.GetBranding`, `platform/treasury.GetTaxCodes`)
  — taxes are sales-tax only; payroll never uses them.
- **Notifications publisher** (`erp.email.requested`/`erp.notification.requested`) — base64 attachment
  normalization preserved.
- **Outbox hardening**: retention/pruning of published rows + DLQ + alert on parked `failed` rows
  (fixes §3); explicit consumer registry already from S1.

## Endpoints
- `/api/v1/approvals/{workflows,steps,requests,approvals}/...`
- `/api/v1/tasks/...`, `/api/v1/hrm/payroll/reports/{p9,p10a,statutory,bank,muster,variance}/...`
- `/api/v1/business/...`, `/api/v1/core/...`, `/api/v1/addresses/...`, `/api/v1/integrations/...`

## Ent schemas
Approvals (typed module), Tasks, business/core/addresses entities, `ExchangeRate`,
`ExchangeRateAPISettings` (secret-ref, not ciphertext) — all `tenant_id`-scoped.

## Events
- OUT: approval lifecycle → `erp.notification.requested`; FX has no event.
- Outbox retention + DLQ operational.

## Acceptance criteria
- Approval workflows are tenant-scoped; role/manager/dept-head approver resolution works (no missing-module
  crash); decomposed workflow types absent.
- Reports produce P9/P10A/statutory/bank/muster/variance matching the Django outputs for a sample tenant/period.
- No code path imports `finance.*`/`crm.*`/`ecommerce.*`; executive dashboard either dropped or S2S-backed.
- FX cron writes rates; provider key sourced from secret store; outbox prunes published + DLQs parked.
- DocumentSequence numbering is gap-free under concurrency (row-lock test).

## Dependencies
- Sprint 1 (rails); Sprints 2-3 supply the entities approvals/reports operate on.
