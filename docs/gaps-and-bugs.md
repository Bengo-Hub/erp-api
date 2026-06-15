# erp-api — Gaps, Bugs, Tech-Debt & Security Issues (Current Django)

> Brutally thorough audit of the **current Django `erp-api`** (the trimmed HR/Ops KEEP set),
> done by reading the actual source. Every item cites real `file:line`. This drives the
> Django → Go revamp: each gap is a requirement for the new service (see `revamp-plan.md`
> and `sprints/`).
>
> Severity legend: **P0** = security / data-integrity / money-correctness (fix in the revamp,
> non-negotiable), **P1** = correctness/architecture, **P2** = tech-debt/cleanliness, **P3** = nit.
>
> Scope audited: `hrm.*`, `approvals`, `task_management`, `reports`, `integrations`,
> `authmanagement`, `business`, `core`, `addresses`, `caching`, `error_handling`,
> `ProcureProKEAPI` (settings/urls/middleware).

---

## 0. Top 10 (the ones that most shape the revamp)

| # | Sev | Issue | Where |
|---|-----|-------|-------|
| 1 | P0 | **No tenant isolation in the query/permission layer** — only `hrm/leave/views.py` references `tenant_id` at all; every other viewset is `Model.objects.all()`. | `hrm/employees/views.py:38,106`; cross-app |
| 2 | P0 | **Real SMTP password present in `.env`** (live value REDACTED here; mailbox `gadmin@masterspace.co.ke`) — compromised, must be rotated. | `.env:37-38` |
| 3 | P0 | **Google OAuth `client_secret` is git-tracked** in `credentials.json`. | `credentials.json:1` (tracked) |
| 4 | P0 | **`ALLOWED_HOSTS = ['*']` hardcoded** + `DEBUG` defaults to `True` + insecure `SECRET_KEY` fallback; `DEBUG=True` forces CORS allow-all-origins-with-credentials. | `settings.py:52,41,26,525-530` |
| 5 | P0 | **Payroll tax tables (`Formulas`) have no `tenant_id`** — statutory rates are GLOBAL across all tenants. | `hrm/payroll_settings/models.py:46-101` |
| 6 | P0 | **Money handled as `float`** in the treasury payout path. | `hrm/payroll/treasury_integration.py:24-45` |
| 7 | P0 | **Permission mixins grant cross-tenant access**: any user with `change_<model>` perm gets `return queryset` (all tenants). | `hrm/employees/permissions.py:188-190,38-40` |
| 8 | P1 | **`approvals` imports a non-existent module** `from hrm.models import Employee` → `ModuleNotFoundError` for role/manager/dept-head approver resolution. | `approvals/models.py:118,149` |
| 9 | P1 | **`Formulas.is_current` single-current invariant is disabled** (save() override commented out) → multiple "current" rate tables, arbitrary selection. | `hrm/payroll_settings/models.py:103-107` |
| 10 | P1 | **Dead imports of decomposed domains** (`finance.*`, `crm.*`, `ecommerce.*`) cause runtime ImportError in the executive dashboard. | `core/analytics/shared_analytics.py:67,115,263,396,450,634`; `core/views.py:858` |

---

## 1. Security (P0/P1)

### 1.1 Committed / on-disk secrets — P0
- **`credentials.json` is git-tracked and contains a live Google OAuth `client_secret`**
  (`GOCSPX-…`) and `client_id`. `credentials.json:1`. It is NOT in `.gitignore` and shows in
  `git ls-files`. **Compromised** — rotate the OAuth client and purge from history. In Go: never
  ship this; OAuth is auth-api's concern, not the ERP's.
- **`.env` holds a real SMTP password** `EMAIL_HOST_PASSWORD=<REDACTED — ROTATE>` for a real mailbox
  `gadmin@masterspace.co.ke` (`.env:37-38`). `.env` *is* gitignored (`.gitignore:1`) so it is not
  in git, **but** the credential is in plaintext on disk and is a real production-style secret →
  rotate. Note also the irony: `settings.py` never loads `.env` (it reads `os.getenv` only), so
  most of these `.env` values (MPESA/STRIPE/KRA/JWT_SECRET) are dead config anyway (see §6.1).
- **`certificates/ProductionCertificate.cer` is git-tracked** (`git ls-files`). A public cert is
  lower-risk than a key, but production cert material should not live in the app repo.
- **`AppSettings.cypher_key` (Fernet key) is stored in the database** and used to encrypt the FX
  provider key (`integrations/utils.py:10,16-17`). Key-in-DB defeats the purpose; the same DB dump
  that leaks the ciphertext leaks the key. In Go: keep the key in a secret store / env, never the DB.

### 1.2 `Crypto` swallows errors and returns the error text as data — P0
`integrations/utils.py:25-27` and `:37-39`: on any failure `encrypt()`/`decrypt()` do
`print(e); return str(e)`. A failed encryption returns the **exception string**, which the caller
may then persist as if it were ciphertext (corrupting the stored FX key), and a failed decrypt
returns an error string that downstream code treats as the plaintext API key. Fail loudly instead.

### 1.3 Insecure defaults that ship to prod — P0
`settings.py`:
- `SECRET_KEY = … or 'django-insecure-…'` (line 26) — insecure fallback if env unset.
- `DEBUG = env_bool('DEBUG', default=True)` (line 41) — **defaults to True**.
- `ALLOWED_HOSTS = ['*']` (line 52) — hardcoded, the env-driven version is commented out (line 51).
- `if DEBUG:` block sets `CORS_ALLOW_ALL_ORIGINS=True` **and** `CORS_ALLOW_CREDENTIALS=True`
  (lines 525-530) — credentialed wildcard CORS is disallowed by browsers and is a CSRF/again-leak
  footgun if DEBUG ever true in prod.
- **No transport/cookie hardening**: no `SECURE_SSL_REDIRECT`, `SECURE_HSTS_SECONDS`,
  `SESSION_COOKIE_SECURE`, `CSRF_COOKIE_SECURE`, `SECURE_PROXY_SSL_HEADER`, `SECURE_CONTENT_TYPE_NOSNIFF`
  anywhere in `settings.py` (these exist only as unused keys in `.env`). Django security checklist
  fails wholesale.

### 1.4 AuthZ is per-user, never per-tenant — P0
`hrm/employees/permissions.py` is the de-facto RBAC for HR:
- `StaffDataFilterMixin.get_queryset` (lines 168-222): a user with `change_<model>` **or**
  `delete_<model>` permission → `return queryset` (lines 188-190) — i.e. **all tenants' rows**.
  No `tenant_id` filter exists anywhere in this mixin.
- `is_hr_or_manager` (lines 26-50) grants write/approve authority to anyone in groups
  `'manager'`, `'admin'`, `'superusers'` or who is `is_staff` (lines 16-23, 38-40) — cross-tenant.
- `IsOwnerOrElevated` / `CanViewSensitiveModule` similarly key off Django model perms with no
  tenant scope (lines 82-85, 127-133).
- `CanViewSensitiveModule.has_permission` returns `True` when `view.queryset is None` (line 121) —
  fail-open for any view that builds its queryset dynamically.
Net: the only thing standing between tenant A and tenant B's payroll is that most viewsets don't
filter at all (so everyone sees everything) — there is no positive isolation. **This is the single
biggest reason for the rebuild.**

### 1.5 Subscription gate / SSO edge cases — P1
- `SubscriptionGatingMiddleware` lets a request through when `auth_claims is None`
  (`sso_middleware.py:128-130`) — correct (defers to 401), but means an attacker who can suppress
  claims parsing bypasses the gate; the real enforcement must be the DRF auth layer + tenant filter.
- `Claims.is_subscription_active()` returns `True` when `sub_status` is absent
  (`sso.py:190-193`) — intentional ("non-gated tenants") but it means a malformed/old token is
  treated as a paying customer. Carry forward deliberately, document it.
- `_assign_service_roles` is skipped entirely if the user already has *any* group
  (`sso.py:268`) — a user demoted in auth-api keeps stale elevated ERP groups forever (roles only
  ever accrete on first login). Revamp: reconcile roles every login (add+remove).

---

## 2. Payroll engine correctness (P0/P1) — the crown jewel to port carefully

`hrm/payroll/services/core_calculations.py`, `hrm/payroll/functions.py`.

### 2.1 Money as `float` into the disbursement/GL path — P0
`treasury_integration.py:24-29` `_f()` casts every amount via `float(v or 0)`; `_line`/`build_payroll_event`
sum and `round()` floats (`:31-62`). PAYE/NSSF/net-pay are then sent to treasury as floats → rounding
drift on real payrolls. Everywhere else uses `Decimal`; this one boundary breaks it. Go: `decimal` end-to-end.

### 2.2 Pervasive "swallow exception, return 0" — P0 (silent wrong payroll)
The engine and `functions.py` are riddled with `except Exception: print(...); return Decimal('0')`
(e.g. `core_calculations.py:97-99,138-140,384-385`; `functions.py:28-30,42-44,62-64,92-94,128-130,144-146,160-162`).
A misconfigured formula doesn't fail the run — it silently zeroes a statutory deduction or a tax
bracket, producing a *plausible but wrong* payslip. There is no "could not compute → abort". Go:
return errors and fail the run; never default a tax to 0.

### 2.3 `is_current` invariant disabled → ambiguous rate selection — P1
`payroll_settings/models.py:103-107`: `Formulas.save()` override that should set all other formulas
`is_current=False` is **commented out**. Combined with `get_effective_formula`'s fallback
`Formulas.objects.filter(query).first()` (`core_calculations.py:95`) when no effective-dated row
matches, two "current" PAYE tables → arbitrary `.first()` selection → wrong tax for the period.

### 2.4 Hardcoded tier/cutover constants inside data-driven engine — P1
- NSSF tier detection keys off literal `lower == Decimal('8000')` (`core_calculations.py:195`) —
  if the configured Tier-2 floor changes (it has, historically), tier-2 silently never accrues.
- `use_nhif_for_period` falls back to a hardcoded `date(2025,1,1)` cutover and
  `_get_legacy_nhif_rate` is a hardcoded 2017-era NHIF table (`:64-65,394-431`) — fine as a labelled
  fallback, but it runs **silently** (only a `logger.warning`) when formulas are missing, so a
  fresh tenant with no seeded SHIF/NHIF formula gets stale 2017 NHIF numbers.

### 2.5 `calculate_income_tax` ignores resolved relief; relief applied elsewhere — P2/P1
`load_formula_rates` returns `relief` but `calculate_income_tax` discards it
(`core_calculations.py:149` unpacks `tax_brackets, relief, _, _` then never uses `relief`).
Personal relief is instead resolved separately via `resolve_personal_relief`. Two code paths can
disagree on the relief amount; consolidate in Go and unit-test against KRA worked examples.

### 2.6 Non-cryptographic, collision-prone reference codes — P1
`functions.py:164-168` `generate_random_code` uses `random.randint(1,99999)` (5-digit space, non-crypto)
for payroll/voucher references. At scale these collide; references should be unique. Go: ULID/UUID
or a `DocumentSequence`-backed counter.

### 2.7 Loan/advance math mutates + saves inside calculation — P1
`get_loan_deduction` (`functions.py:227-265`) increments `amount_repaid`, `interest_paid`,
`no_of_installments_paid` and calls `loan.save()` **inside a "calculate" function**. If the enclosing
payslip generation later fails/rolls back partially (or runs twice), repayment state desyncs from the
payslip. Calculation must be pure; persistence must be one atomic step. (Also `calculate_interest`
reducing-balance loop, `:199-206`, does float-free Decimal but is O(installments) per payslip.)

### 2.8 Disburse path is non-idempotent and retries POST — P0
- `PayrollDisburseView` (`hrm/payroll/disburse_view.py`) has **no idempotency key / no guard against
  re-running the same period** — POST twice and you publish `erp.payroll.processed` twice and request
  a second disbursement. The only guard is marking scheduled expense claims paid (`:52-58`), not the
  payouts themselves.
- The S2S client retries POST on 502/503/504 (`service_client.py:128-131`, `allowed_methods`
  includes POST, `raise_on_status=False`) — a treasury timeout after it accepted the payout can
  trigger a **double payout**. Disburse must carry an idempotency key and treasury must dedupe.
- `publish_and_disburse` publishes the GL event first, then disburses best-effort
  (`treasury_integration.py:76,92-99`); a disburse failure leaves a GL journal with no matching
  payout and the API still returns 200 (`disbursed:false`). Acceptable per design, but the response
  shape hides it from naive callers.

### 2.9 `handle_payroll_disbursed` over-marks payslips — P1
`treasury_integration.py:122-126`: marks `published=True` for **every** payslip whose
`payment_period__startswith` the 7-char period and matches tenant — it ignores `outlet_id` and the
specific `batch_ref`. A per-outlet disbursement marks *all* outlets' payslips for that month paid.
Filter by the batch's outlet (or carry payslip IDs in the event).

---

## 3. Eventing / integrations (P1/P2)

- **Consumers silently do nothing if a module isn't imported.** `CONSUMER_HANDLERS` is filled in
  `integrations/apps.py:14-23` (`ready()`), but `consume_events` exits with "No consumer handlers
  registered" (`consume_events.py:28-30`) if app `ready()` hasn't run in that process / import order
  differs. Registration-by-side-effect is fragile. Go: explicit consumer registry wired at startup.
- **No dead-letter / poison-message handling.** `_consume_async` (`events.py:155-168`) acks on
  success and just logs on handler exception (no `nak`, no DLQ, no max-deliver) — a permanently
  failing message is logged forever or (depending on stream policy) blocks. The outbox drainer parks
  rows `failed` after `EVENTS_MAX_ATTEMPTS` (`events.py:123-127`) with **no alerting and no retry of
  parked rows**.
- **Outbox has no retention/pruning.** `EventOutbox` rows accumulate (`status=published` never
  deleted). The drainer fetches `STATUS_PENDING` ordered by `created_at` with no index hint; at scale
  this table grows unbounded. (See platform "Outbox retry/retention model" memory for the target pattern.)
- **Durable name derivation is lossy.** `events.py:166` maps `*`/`>` → `all`, so `auth.tenant.>` and
  `auth.tenant.*` would collide on the same durable. Minor today (only one is used).
- **`drain_outbox` connects/drains a fresh NATS conn per batch** (`events.py:112,134`) — connection
  churn under load. Go `shared-events` OutboxPoller holds a persistent JS context.

---

## 4. Multi-tenancy & data model gaps (P0/P1)

- **HR tables have no `tenant_id`.** Per `erd.md`, isolation is *derived* via
  `Employee.organisation → business_details.tenant_id`. Every list/report joins through that chain
  (e.g. `disburse_view.py:38` `employee__organisation__tenant_id`), which only works if the viewset
  bothers to filter (most don't — §1.4). `Formulas`, `ApprovalWorkflow`, `PublicHoliday`, all the
  singletons, etc. are fully global.
- **`ApprovalWorkflow` is global and lists decomposed workflow types.** `approvals/models.py:16-29`
  still offers `purchase_order`, `expense`, `invoice`, `requisition` — all owned by inventory/treasury
  now. Workflows are not tenant-scoped, so one tenant's payroll-approval matrix applies to all.
- **GenericForeignKey approvals.** `Approval`/`ApprovalRequest` use `content_type_id`+`object_id`
  (`erd.md §10`) pointing at arbitrary tables, several of which were decomposed out → dangling rows.
  Go: typed `module` enum + UUID `object_id` (inventory-api pattern).
- **Singletons assume one business.** `GeneralHRSettings`, `RegionalSettings`, `ESSSettings`,
  `ExpenseClaimSettings` are `pk=1` singletons (`erd.md §5,§3,§7,§6`) — there is exactly one across all
  tenants. Must become per-tenant in Go.
- **Mixed decimal precision.** Payroll uses `DecimalField(14,2)` and `(14,4)` interchangeably
  (`payroll_settings/models.py:33-34,71-74` vs `Payslip`/`Deductions` `(14,4)`), and `djmoney`
  `MoneyField` for `BenefitTaxes`. Normalize to one internal precision (recommend 18,4) in Go.

---

## 5. Dead code / decomposition leftovers (P1/P2)

- **`core/analytics/shared_analytics.py`** imports `finance.payment.models`, `finance.expenses.models`,
  `finance.invoicing.models`, `crm.contacts.models` (lines 67,115,263,396,450,634) — **all deleted
  apps**. `executive_analytics.py:132` imports `ecommerce.stockinventory.models`. These are lazy
  imports inside `try/except`, so the dashboard at `core/views.py:858-891` (`ExecutiveAnalyticsService`)
  returns silently-empty/broken sections instead of failing. Either delete the dashboard or point it
  at the owner services via S2S. **Do not port** — HR/ops dashboards only in Go.
- **`tools/test_product_list.py`, `tools/find_zone.py`** import `ecommerce.product`/`ecommerce.stockinventory`
  — broken scripts referencing deleted apps. Delete.
- **Stale Celery routes** in `settings.py:176-190` for `ecommerce.order.tasks`, `finance.*.tasks`,
  `notifications.services.*` — all decomposed; dead routing config.
- **`settings.py:269`** commented `finance.accounts.middleware.TaxFormulaMiddleware` left in the
  MIDDLEWARE list as a comment; `hrm/payroll_settings/middleware.py:TaxFormulaMiddleware` is the live one.
- **`urls.py:23-24`** unconditionally imports `apscheduler` + `check_expiring_contracts` at module
  load, but the scheduler that would use them is commented out (`:97-99`) — dead import that still
  pulls a hard dependency; contract-expiry notifications are therefore **not running at all**.
- **`core/serializers.py:133`, `core/models.py:205`** carry `# Use: from crm.campaigns...` comments
  pointing at deleted modules.
- **Three middlewares exist solely to lazily auto-create config rows** on every request:
  `PayrollFormulaMiddleware`, `payroll_settings TaxFormulaMiddleware`, attendance `DefaultShiftMiddleware`
  (`settings.py:270-272`). Per-request "ensure exists" is a hot-path anti-pattern (extra queries on
  every call). Go: seed once via `cmd/seed`, not middleware.

---

## 6. Configuration & ops debt (P2)

- **`.env` is never loaded** by `settings.py` (it uses `os.getenv` only; only `integrations/utils.py:9`
  and stray modules call `load_dotenv()`), so the entire `.env` (DB password, MPESA/STRIPE/KRA/JWT,
  cookie-secure flags) is **ignored** unless those vars are also exported into the process env. This is
  a trap: operators editing `.env` see no effect. Either load it or delete it.
- **`requirements.txt` has zero version pins** (except a handful) and is hugely bloated with
  decomposed-domain deps: `stripe`, `twilio`, `africastalking`, `firebase-admin`, `fcm-django`,
  `pushjack`, `openai`, `scikit-learn`/`scipy`, `polars`, `matplotlib-inline`, `pyppeteer`,
  `pyHanko`, M-Pesa stack, `boto3` (lines throughout). Supply-chain + image-bloat risk. The Go
  rebuild eliminates the entire Python dependency surface.
- **`disable_existing_loggers: True` with root at `DEBUG`** (`settings.py:278,293`) — silences
  library loggers and floods stdout with DEBUG in every environment (no env gating of log level).
- **`api_root` view (`urls.py:30-43`) advertises `/admin/`** publicly; Django admin (`jazzmin`) is
  enabled in a service that is otherwise a headless API behind SSO.
- **`CONN_MAX_AGE=600`** with no `CONN_HEALTH_CHECKS` — stale connections after DB restarts.

---

## 7. Error handling & base viewsets (P2)

- **`BaseModelViewSet` leaks raw exception text to clients.** `core/base_viewsets.py:129-133,
  163-167,206-213,270-283` pass `error_id=str(e)` (the raw exception message, sometimes a SQL/value
  error) into the API response. Information disclosure + inconsistent contract.
- **`BaseModelViewSet` string-matches `'404' in str(e)`** (`:157,274,326`) to decide not-found — brittle
  (a record whose field literally contains "404" misroutes). Use typed exceptions.
- **`EmployeeViewSet` silently coerces PUT into PATCH** (`hrm/employees/views.py:112-120`) — a full
  replace request behaves as partial, so clients can't clear fields; surprising and undocumented.
- **`UploadEmployData` returns `str(e)` with 500** on any failure (`employees/views.py:92-93`) and
  resolves the org via `Q(owner=user)|Q(employees__user=user)` (`:74`) with no tenant check — an
  employee of business A could import into business A only by luck of FK, not by design.
- **316 `except Exception` blocks across 60 files** (grep) — the codebase's dominant error strategy is
  swallow-and-continue, which is exactly why payroll can produce silently-wrong numbers (§2.2).

---

## 8. Testing & misc (P2/P3)

- Test coverage is thin and uneven: real tests exist for payroll generation/statutory config
  (`hrm/payroll/tests/`), leave accrual, onboarding, shift planner, business timezone serializer —
  but employees, approvals, integrations (`integrations/tests.py`), authmanagement, core viewsets are
  mostly empty stubs. The money-critical disburse/idempotency path (§2.8) has no test.
- `generate_payslip_demo.py`, `playground.py`, `test_invoice.pdf` (110 KB) committed at repo root —
  scratch artifacts that shouldn't ship.
- `Formulas.types` label typos: `"Fridge Benefit Tax Formula"` (×2, `payroll_settings/models.py:51,58`)
  — cosmetic but baked into choices/DB.
- `hrm/reports/` is an **empty package** (only `__init__.py`); the `reports/` top-level dir is also a
  stub. Reporting actually lives in `hrm/payroll/services/reports_service.py` + `core` dashboards. The
  "reports" KEEP module is effectively un-built — the Go revamp must define it for real.
- `business/models.py:Bussiness` misspelled model name and `finacial_year_start_month` typo
  (`erd.md §2`) — carried in `db_table='business_details'`; rename cleanly in Go.

---

## 9. How each gap maps into the Go revamp

| Gap cluster | Fixed in Go by | Sprint |
|---|---|---|
| §1.1–1.3 secrets/insecure defaults | secrets via env/secret-store only; httpware secure defaults; no admin; no committed creds | S1 |
| §1.4 cross-tenant authZ | mandatory `tenant_id` column + handler-level `claims.TenantID` filter (inventory-api pattern); role reconcile every login | S1, S4 |
| §2 payroll correctness | port engine to `decimal`, errors-not-zeros, idempotent disburse w/ key, single-current rate tables, **tenant-scoped versioned rate tables** | S2 |
| §3 eventing | `shared-events` OutboxPoller + explicit consumer registry + DLQ + retention | S1, S4 |
| §4 data model | UUID PKs, `tenant_id` everywhere, typed approvals, per-tenant settings, one decimal precision | S1–S4, migrator S5 |
| §5 dead code | simply not ported; dashboards via S2S to owner services | all |
| §6–8 ops/test debt | pinned Go deps, structured zap logging, real test suites incl. money paths | all |

See `revamp-plan.md` for the executive plan and `sprints/` for sequencing.

---

## Prod migrate-ownership + Atlas-revisions baseline (discovered 2026-06-15)

**Bug:** Versioned migrations never apply in prod. Root cause chain:
1. There is **no `atlas_schema_revisions` table** in prod `bengo_erp` — the schema was created
   by the cutover (as `admin_user`), so Atlas has no baseline and tries to replay *all*
   migrations from scratch on every deploy.
2. The migrate Job connects as **`erp_user`** (the legacy Django role, from the reused
   `erp-api-env` secret), which has DML but **does not own** the tables (`admin_user` owns all
   93). The first DDL (`CREATE INDEX` on `exchange_rates`) fails: `must be owner … (42501)`.

**Impact:** any versioned migration silently fails in prod. E.g. the FX tenant-scoped unique
index never landed (the old non-tenant `exchangerate_base_currency_quote_currency_rate_date`
UNIQUE index — the multi-tenant FX bug — was still present).

**Applied now (targeted):** dropped the old non-tenant unique index and created
`exchangerate_tenant_id_base_currency_quote_currency_rate_date` (UNIQUE on
tenant_id,base_currency,quote_currency,rate_date) as `admin_user`. FX multi-tenant uniqueness
now matches the ent schema. (Table was empty — zero risk.)

**Systemic follow-up (devops):** make migrations run as the table owner + baseline Atlas:
- Add a migrate-only DSN (`POSTGRES_MIGRATE_URL`) using `admin_user` to the migrate Job (keep
  the runtime `erp_user` least-privilege), OR `REASSIGN OWNED BY admin_user TO erp_user` within
  `bengo_erp`.
- Baseline the revisions table (`migrate apply --baseline` / Atlas `--allow-dirty`) so existing
  schema is marked applied and only *new* migrations run.
Until then, schema changes must be applied manually as `admin_user`.
