# ERP Data Migration Runbook (legacy Django `bengo_erp` → Go/Ent)

> Operator runbook for the **Sprint 5 cutover**. The authoritative table→Ent mapping, FK
> ordering and Django-type gotchas live in [`data-migration.md`](./data-migration.md); this
> file is the **exact step sequence** to run the migrator (`cmd/migrate-data`) against prod.
>
> Critical context (plan §0c): prod DB `bengo_erp` currently holds the **legacy Django schema
> (158 tables)**. The new Ent tables live in the **SAME database** under different names, so the
> migrator reads OLD Django tables and writes NEW Ent tables in one DB — it is **not** a
> cross-database copy. The migrator is **idempotent** (deterministic UUIDv5 PKs + upsert /
> skip-if-exists), so it is safe to re-run during rehearsal and for the final delta.

## What the migrator does (and does not) move

**In scope (KEPT HR/Ops domains).** Each runs in FK-dependency order:

| # | Source (Django) | Dest (Ent) | Notes |
|---|---|---|---|
| 1 | `departments` | `departments` | reference; `tenant_id` NULL = global |
| 2 | `jobtitles` | `job_titles` | global ref → needs `--default-tenant` |
| 3 | `business_details` | `company_settings` | slim; 1 row/tenant; drops branding/tax/pickup |
| 4 | `document_sequences` | `document_sequences` | **carries `current_sequence`** (numbering won't restart) |
| 5 | `leave_leavecategory` | `leave_categories` | global ref → needs `--default-tenant` |
| 6 | `employee` | `employee` | HR FK hub; tenant backfilled; `user_id` NOT carried (SSO JIT) |
| 7 | `employee_bank_accounts` | `employee_bank_accounts` | bank masters dropped, details kept as fields |
| 8 | `employee_hr_details` | `hr_details` | remaps job_title/department/reports_to |
| 9 | `employee_salary_details` | `salary_details` | rates recomputed by service (not carried) |
| 10 | `employees_contract` | `contract` | `duration_months` recomputed by service |
| 11 | `payslips` | `payslip` | **golden-master parity table** — exact decimals |
| 12 | `leave_leaverequest` | `leave_request` | status → Ent enum; remaps category/approver |

**Deliberately NOT moved** (see `data-migration.md §4`): decomposed-domain tables
(finance/inventory/ordering/projects/CRM/assets), `auth_*` RBAC (re-seeded via `cmd/seed`,
not copied), `CustomUser` rows (SSO JIT recreates from the JWT `sub`), `published` outbox
rows, Fernet FX ciphertext (re-key), and bank_institution/bank_branch masters.

> The migrator covers the **core HR/payroll chain** that the parity gate validates. Additional
> KEPT tables (attendance, recruitment, training, appraisals, performance, tasks, approvals,
> loans/advances/deductions/benefits/earnings) follow the **same per-table pattern** in
> `cmd/migrate-data/migrate_*.go` — extend there before the real run if those tables hold prod
> rows (confirm via the per-table counts in step 1).

## Transform guarantees

- **Money/decimal**: parsed via `shopspring/decimal`, **never float** (gaps §2.1).
- **IDs**: legacy `bigint` PK → deterministic **UUIDv5(`"<table>:<id>"`)**. Same legacy row →
  same UUID on every run (idempotency) and FK remap needs no side table.
- **Tenant backfill**: every HR row's `tenant_id` is derived from
  `employee.organisation → business_details.tenant_id`. Rows that resolve to **no tenant** are
  **skipped** (counted in the report) — never written with a guessed tenant. Supply
  `--default-tenant=<uuid>` to place such rows (and the global reference tables) explicitly.
- **Datetimes**: normalized to `Africa/Nairobi`.
- **Idempotent**: re-running skips rows already present (by deterministic UUID / natural key).
- **Degrades cleanly**: a missing source table or column is skipped with a warning (so a
  dry-run runs on a DB without the full legacy schema).

## Flags

```
--dry-run              read + transform + report counts, perform NO writes
--only=<table>         migrate only one legacy table (e.g. --only=employee)
--verbose              log every per-row skip decision
--default-tenant=UUID  tenant for global reference rows + HR rows with NULL organisation
```

The migrator reads `POSTGRES_URL` (fallback `POSTGRES_MIGRATE_URL`, then a local default).
**Never hardcode credentials** — the DSN comes from env / the k8s secret.

---

## Prod run — step by step

### 0. Prerequisites
- `kubectl` access to the cluster (per the dev-workflow memory: prod Postgres is the shared
  `postgresql-0`, with a per-service DB `bengo_erp`).
- The Go toolchain (or the built `migrate-data` binary / image).
- A maintenance window: HR is not real-time critical, so this is an **offline cutover**.

### 1. Assess prod (sizing the migration)
Port-forward to prod Postgres (no creds in shell history — pull them from the secret):
```bash
kubectl -n <ns> port-forward svc/postgresql 5432:5432 &
# Pull the password from the k8s secret into an env var (do NOT echo it):
export PGPASSWORD="$(kubectl -n <ns> get secret <pg-secret> -o jsonpath='{.data.postgres-password}' | base64 -d)"
export POSTGRES_URL="postgres://<user>:${PGPASSWORD}@localhost:5432/bengo_erp?sslmode=disable"
```
Get real per-table row counts to confirm which in-scope tables actually have data:
```bash
psql "$POSTGRES_URL" -c "SELECT relname, n_live_tup FROM pg_stat_user_tables ORDER BY 2 DESC;"
```

### 2. Backup (the rollback)
```bash
pg_dump "$POSTGRES_URL" -Fc -f bengo_erp_pre_migration_$(date +%Y%m%d_%H%M).dump
```
Keep this dump until parity is confirmed in prod for one full payroll cycle.

### 3. Apply the Ent/Atlas migrations (create the new tables alongside the Django tables)
```bash
POSTGRES_MIGRATE_URL="$POSTGRES_URL" go run ./cmd/migrate     # versioned Ent migrations
POSTGRES_URL="$POSTGRES_URL" go run ./cmd/seed                # re-seed RBAC roles + HR perms
```
New Ent table names differ from Django table names → **no collision** in `bengo_erp`.

### 4. Dry-run on a RESTORED COPY first (never first-run against live prod)
Restore the dump into a scratch DB and point the migrator at it:
```bash
createdb bengo_erp_rehearsal
pg_restore -d bengo_erp_rehearsal bengo_erp_pre_migration_*.dump
POSTGRES_MIGRATE_URL="postgres://.../bengo_erp_rehearsal?sslmode=disable" go run ./cmd/migrate
POSTGRES_URL="postgres://.../bengo_erp_rehearsal?sslmode=disable" \
  go run ./cmd/migrate-data --dry-run --default-tenant=<operating-tenant-uuid> --verbose
```
Read the **reconciliation report**: `written + skipped == read` for every table, and the
`SKIPPED` column for `employee` should be 0 unless there are legitimately un-tenanted rows
(decide: assign `--default-tenant` or quarantine them).

### 5. Run for real on the rehearsal copy, then verify parity
```bash
POSTGRES_URL="postgres://.../bengo_erp_rehearsal?sslmode=disable" \
  go run ./cmd/migrate-data --default-tenant=<operating-tenant-uuid>
```
Then run the **parity gate** (sprint-5 acceptance criteria):
- Row-count parity per in-scope table (report vs `pg_stat_user_tables`).
- FK integrity: zero orphans (every `payslip.employee_id`, `hr_details.employee_id`, … resolves).
- **Tenant assertion**: `SELECT count(*) FROM employee WHERE tenant_id IS NULL` → 0 (and every
  HR table likewise).
- **Payroll golden-master**: re-run the Go payroll engine for the last closed period for N
  employees; compare net/PAYE/NSSF/SHIF/levy against the migrated `payslip` rows — zero-cent diff.

Re-run the migrator on the same rehearsal DB to prove **idempotency**: the second run must
report `written=0, skipped=<all>` for every table.

### 6. Cut over (production)
1. **Freeze writes** on the Django app (scale to 0 / read-only).
2. **Final delta** ETL against live prod:
   ```bash
   POSTGRES_URL="$POSTGRES_URL" go run ./cmd/migrate-data --default-tenant=<operating-tenant-uuid>
   ```
   (Idempotent — only new rows since the rehearsal snapshot are written.)
3. Re-run the **parity gate** against prod.
4. **Flip ingress** to the Go `erp-api`.
5. **Drain pending outbox** / smoke test: `/auth/me`, employee list, payroll preview, `/core/health`.

### 7. Spot-check, then drop the legacy Django tables
After smoke tests pass and a full payroll cycle reconciles, drop the legacy Django tables
(they remain in the step-2 dump for rollback). Keep the Django app read-only until then.

## Rollback
Restore the step-2 `pg_dump` into `bengo_erp` (or repoint ingress to the still-running
read-only Django app). Because the migrator only **adds** new Ent tables and never mutates the
Django tables, rollback before step 7 is simply "ignore the Ent tables / flip ingress back".

## Local dry-run (build verification, no prod)
Against a local `bengo_erp` that has the Django schema but no business rows, the dry-run
reports `read=0` for every table and `parity: OK` — confirming connectivity, the FK-ordered
table walk, and the reconcile report without touching prod:
```bash
POSTGRES_URL="postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable" \
  go run ./cmd/migrate-data --dry-run
```
