# erp-api Data Migration Plan (Django `bengo_erp` → Go service schema)

> Concrete plan to migrate data from the existing Django Postgres DB into the new Go (Ent/Atlas)
> schema. Table-by-table mapping, type notes, sequencing/FK order, gotchas.

---

## 0. Current state of the data

- **Local dev DB** `bengo_erp` (PostgreSQL 17, `localhost:5432`, `postgres/postgres`): full schema
  (**158 tables**) but transactional data is **cleared** — only `auth_group` (14 rows = service
  roles) and `auth_permission` (592 rows) are populated; `employee`, `payslips`, `business_details`,
  `integrations_eventoutbox`, etc. are empty. Use local only for schema reconstruction/dev.
- **Production DB** (shared `postgresql-0`, per-service DB, see memory: Postgres topology) holds the
  real tenant HR/payroll data. The real migration runs against a **prod snapshot/dump**, not local.
- Settings: DB name from `DB_NAME` env (default `bengo_erp`); `.env` is NOT auto-loaded.

Get real prod counts before migrating:
```bash
pg_dump -U <user> -h <prod-host> bengo_erp -n public --schema-only > schema.sql   # reference
psql ... -c "SELECT relname,n_live_tup FROM pg_stat_user_tables ORDER BY 2 DESC;"  # row counts
```

---

## 1. Strategy

Two-phase, **offline cutover** (HR/payroll is not real-time critical):

1. **Schema-first in Go**: author Ent schemas (`erd.md`), generate, apply Atlas migrations to an
   empty target DB (`erp` database, new per-service DB).
2. **ETL backfill**: a one-shot Go `cmd/migrate-data` (or SQL `INSERT ... SELECT` via `postgres_fdw`)
   copies rows in FK-dependency order, mapping Django types → Go/Ent types and rewriting PKs.

### ID strategy (critical decision)

Django uses `BIGSERIAL` integer PKs; the platform Go services use **UUID** PKs.
Recommended: **assign new UUIDv7 PKs**, keep a per-table `legacy_id BIGINT` column (indexed) during
migration to remap FKs, then drop `legacy_id` after verification. Alternative (faster, less clean):
keep integer PKs for HR tables and only UUID-key the tenant/outlet shadows + outbox (already UUID).
Pick UUID for consistency with inventory-api/treasury-api.

The few tables already UUID-keyed map 1:1: `integrations_eventoutbox`, `task_management_task`,
`error_handling_error`, `authmanagement_authtenant`, `authmanagement_authoutlet`,
`business_details.tenant_id`, `employee.outlet_id`.

### Tenant backfill

Most HR rows have **no `tenant_id` column today** (multi-tenant isolation gap — see
`gaps-and-bugs.md`). During migration, derive `tenant_id` for every HR row via
`Employee.organisation → business_details.tenant_id`, and stamp it onto the new tenant-scoped tables.
Rows with NULL organisation must be assigned to a default/operating tenant or quarantined.

---

## 2. Django-specific type mapping

| Django/PG type | Go/Ent type | Notes |
|---|---|---|
| `BigAutoField` (bigserial) | `uuid` (UUIDv7) + `legacy_id bigint` | remap FKs via legacy_id |
| `UUIDField` | `uuid.UUID` | 1:1 |
| `DecimalField(max_digits, decimal_places)` | Ent `field.Other` decimal (string) | **never float**; normalize payroll `(2)` vs `(4)` to a single precision (recommend 18,4 internal, 18,2 display) |
| `MoneyField` (djmoney) | decimal + currency string | djmoney stores `<field>` + `<field>_currency` columns — migrate both |
| `CharField`/`TextField` | `string` | |
| `BooleanField` | `bool` | |
| `DateField`/`DateTimeField` | `time.Time` (date-only via type) | TZ = `Africa/Nairobi`, `USE_TZ=True` |
| `JSONField` | `field.JSON` / typed struct | e.g. `Formulas.deduction_order`, `AttendanceRule.public_holidays`, `Task.input_data` |
| `ImageField`/`FileField` | `string` path | copy media files separately (PVC); store relative path (see media-image convention memory) |
| `PhoneNumberField` | `string` (E.164) | |
| `CountryField` | `string` (ISO-2) | |
| `TimeZoneField` | `string` | |
| `ContentType` + `object_id` (GenericFK) | `enum module` + `uuid object_id` | re-map approvals to typed module (see below) |
| encrypted `access_key` (Fernet `gAAAAA…`) | re-encrypt or re-enter | do NOT carry Fernet ciphertext; re-key via new secret mgmt |

---

## 3. Load order (FK dependency sequencing)

Insert in this order so FKs resolve. (`→` = depends on.)

```
1.  RBAC + identity
    auth_group, auth_permission, auth_group_permissions        (roles/perms — re-seed via cmd/seed instead of copy)
    authmanagement_authtenant, authmanagement_authoutlet       (UUID; or re-sync from auth-api)
    authmanagement_customuser                                  (keep external_id; remap id->uuid)
    authmanagement_customuser_groups, *_user_permissions
    authmanagement_userpreferences
2.  core reference
    regions, departments, project_categories, projects,
    bank_institutions, bank_branches, core_exchangerate,
    core_regionalsettings, core_appsettings
3.  business
    business_location, business_details (tenant_id),
    business_branches, business_branding_settings, taxrates,
    prefix_settings, document_sequences, service_types,
    product_settings, sale_settings, pickup_stations
4.  addresses
    delivery_regions, address_book, address_validations
5.  HR core
    jobtitles, job_groups, workers_unions,
    employee  (FK user, organisation),
    employee_bank_accounts, employee_salary_details,
    employee_hr_details, employees_contract,
    employee_contact_details, employee_kin_details, employee_documents
6.  attendance
    hrm_work_shifts, hrm_work_shift_schedules, hrm_shift_rotations(+_shifts),
    hrm_attendance_rules, hrm_attendance_records, hrm_off_days,
    ess_settings(+_exempt_roles), attendance_timesheet, attendance_timesheetentry,
    hrm_shift_rosters, hrm_shift_roster_slots, hrm_shift_assignments, hrm_staff_shift_overrides
7.  payroll settings (before payroll txns)
    payroll_settings_relief, *_payrollcomponents, *_formulas, *_formulaitems,
    *_splitratio, *_benefittaxes, *_withholdingtax, *_loans, *_repayoption,
    *_severancepay, *_generalhrsettings, *_defaultpayrollsettings(+M2M),
    *_marketlengingrates, *_scheduledpayslip(+_recipients)
8.  payroll txns
    employee_loans, employee_advances, employee_losses_and_damages,
    employee_deductions, employee_benefits, employee_earnings,
    employee_expense_claims, payroll_claimitems, payroll_expensecode,
    payroll_expenseclaimsettings, payslips, payroll_payslipaudit, hrm_custom_reports
9.  leave
    leave_leavecategory, leave_leaveentitlement, leave_leaverequest,
    leave_leavebalance, leave_leavelog, hrm_public_holidays
10. appraisals/performance/recruitment/training
    appraisals_*, performance_*, hrm_recruitment_*, hrm_employee_onboarding,
    hrm_onboarding_tasks, hrm_training_*
11. approvals (last — GenericFK to many tables)
    approval_workflows, approval_steps, approvals, approval_requests
12. system
    integrations_eventoutbox (skip published rows), integrations_exchangerateapisettings (re-key),
    task_management_*, error_handling_*  (optional — historical; may archive instead)
```

---

## 4. Per-area mapping notes & gotchas

- **RBAC (`auth_group`/`auth_permission`)**: do NOT copy verbatim. 592 permissions include stale
  decomposed-module perms (see `prune_decomposed_permissions`). In Go, **re-seed** the 14 roles +
  HR-scoped permissions via `cmd/seed` (mirror `seed_rbac_roles.py:ROLE_SPECS`). Only migrate
  user→role assignments (by `external_id`).
- **CustomUser**: most users are SSO shadows. Prefer **not** migrating users at all — let JIT
  provisioning recreate them from JWT `sub`. Migrate only fields that aren't in the JWT
  (signature image, preferences, `must_change_password`) keyed by `external_id`.
- **djmoney columns**: `BenefitTaxes.fixed_limit` etc. have companion `_currency` columns; migrate
  both into a decimal+currency pair.
- **Singletons** (`GeneralHRSettings`, `RegionalSettings`, `ESSSettings`, `ExpenseClaimSettings`,
  pk=1): migrate the single row; in Go store per-tenant (currently global → becomes tenant-scoped).
- **Approvals GenericFK**: `content_type_id`+`object_id` reference arbitrary tables. Build a
  ContentType→module map; only Payslip/leave/contract/appraisal targets are in scope (others were
  decomposed). Rewrite to `module` enum + remapped `object_id` UUID; drop dangling rows whose
  target table no longer exists.
- **EventOutbox**: migrate only `pending` rows (re-publish after cutover); discard `published`.
- **Encrypted FX `access_key`**: Fernet ciphertext is tied to `AppSettings.cypher_key`. Re-enter the
  provider key into the new secret store; do not carry ciphertext.
- **Auto-calculated fields** (`SalaryDetails.hourly_rate/daily_rate`, `Contract.contract_duration`,
  `RepayOption.installment_amount`, `ClaimItems.amount`): recompute in Go on insert rather than
  trusting stale stored values.
- **Effective-dated formulas**: preserve `effective_from/effective_to/is_current/version` exactly —
  payroll correctness for historical periods depends on them.
- **Media files**: copy `media/` (passports, signatures, logos, stamps, documents, resumes) to the
  new PVC; rewrite `ImageField`/`FileField` paths to the Go service's relative convention.
- **Sequences**: after backfill, if keeping any integer PKs, `setval` sequences past max.
  `DocumentSequence.current_sequence` must be carried so document numbering doesn't restart.

---

## 5. Validation & cutover

1. Row-count parity per table (source vs target) excluding deliberately-skipped tables.
2. FK integrity: zero orphan FKs (every employee→user/organisation, payslip→employee resolves).
3. Spot-check: re-run the payroll engine for the last closed period for N employees and compare
   net pay / PAYE / NSSF / SHIF against the migrated `payslips` row.
4. Tenant isolation: every HR row has a non-null `tenant_id`.
5. Cutover: freeze writes on Django → final delta ETL → flip ingress to Go → run `drain_outbox`
   for any pending outbox rows → smoke test `/auth/me`, employee list, payroll preview.

---

## 6. Tooling options

- **Preferred**: Go `cmd/migrate-data` using `postgres_fdw` foreign tables (`legacy.*`) +
  Ent client for typed inserts, in a single transaction per table batch.
- **Alternative**: per-table `INSERT INTO new.table SELECT ... FROM legacy.table` with explicit
  column mapping + `gen_random_uuid()` PK + a `legacy_id` join table for FK remap.
- Keep the ETL **idempotent** (upsert on `legacy_id`/`external_id`) so it can be re-run during the
  rehearsal/cutover window.
