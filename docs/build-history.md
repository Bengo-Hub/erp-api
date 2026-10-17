# erp-api build history

What was built, in the order it was built, and the design rules each area settled. Open work is in
[backlog.md](backlog.md). All areas below are done on `main` and tenant-scoped.

## Foundation

- Server, migrate and seed commands, config, httpware middleware chain (request id, recovery, CORS
  without credentialed wildcards, zap logging).
- `platform/auth` and `services/usersync`: JWKS validation, user, tenant and outlet shadows, roles
  reconciled on every login (add and remove).
- Tenant and outlet context: the tenant comes from the claims, a platform owner may override with
  `?tenantId=`, the outlet comes from `X-Outlet-ID`. Subscription gate refuses mutations when inactive.
- Transactional outbox (`outbox_events` + `shared-events` poller), explicit consumer registry for
  `auth.tenant.*`, `auth.outlet.*` and `auth.user.*`.
- `GET /api/v1/auth/me/` returns service roles and permission codes. `cmd/seed` writes the HR
  permissions and 14 system roles.

## Employees and payroll

- `employees`: employee root with salary, HR details, contracts, contacts, next of kin, documents,
  bank accounts (single primary enforced in a transaction), job titles and groups, workers union.
  Derived rates are recomputed on write.
- `payrollengine`: pure, decimal, fails loudly instead of returning zero. Progressive PAYE with
  personal relief, tiered NSSF, SHIF and NHIF with a configured cutover, Housing Levy, recoverables
  capped at the outstanding balance, deduction phasing. A golden-master test pins gross 100,000 to net
  71,617.65.
- `payrollsettings`: effective-dated formulas, reliefs and components; one current row per
  (tenant, type, category) enforced by a partial unique index. National defaults are seeded once under
  the system tenant (`cmd/seed-payroll`) and inherited by tenants until they override. Payroll tax
  never reads treasury's sales tax codes.
- Payroll to treasury: publish `erp.payroll.processed`, then S2S `POST /payouts/disburse` with an
  idempotency key. Disbursement is synchronous and payslips are marked published on success. Amounts
  travel as decimal strings.

## Later additions

- Attendance deductions: late and unexcused absence are computed into reviewable `AttendanceDeduction` rows, HR approves or waives them, and the run takes approved amounts off gross before statutory deductions.
- Background payroll runs with live progress (`PayrollRunJob`, Server-Sent Events, one active run per tenant).
- External expense claims and a per diem policy so other services (logistics staff riders) raise claims here.
- Employee lookup endpoint for other services' pickers.
- Payroll run inputs loaded in batches instead of per employee.

## Leave, attendance, recruitment, training, appraisals, performance

- `leave`: categories, entitlements, requests (pending, approved, rejected, cancelled), balances, logs,
  tenant-scoped public holidays. Idempotent accrual with capped carryover on a goroutine
  (`LEAVE_ACCRUAL_INTERVAL`) and `POST /leave/accrue`. Decisions emit `erp.notification.requested`.
- `attendance`: shifts, records, priority-ordered rules, rotations, off days, per-tenant ESS settings,
  timesheets, shift planner. Late detection and overtime split are a pure decimal package. A default
  shift is seeded once per tenant.
- `recruitment`: postings, candidates, applications (state machine), onboarding with a 10 item
  checklist; hiring can create the employee atomically. Resume upload is in place.
- `training`: courses, enrollments (capacity enforced), evaluations. `appraisals` and `performance`:
  cycles, templates, goals, metrics, reviews with state machines and 0 to 5 decimal ratings.

## Approvals, tasks, reports, business config

- `approvals`: typed module enum, tenant-scoped workflows and steps, approver resolution by user, role,
  manager, department head or owner, approve, reject and escalate, outbox events. Wired into leave and
  appraisals.
- `tasks`: task tracker with comments and logs and a status state machine.
- `reports`: P9, P10A, statutory deductions, SHIF, NHIF, NSSF, NITA, withholding tax, bank schedule,
  muster roll, variance, and HR analytics (headcount, hires, turnover, expiring contracts, payroll trend,
  overtime, leave liability).
- `business` and `orgsettings`: company settings and gap-free document sequences. Branding is read
  through from auth-api and cached. FX rates and the scheduled fetch live in `fx`; the provider key
  comes from the secret store, not the database.

## Data ownership decisions

- Not owned here: projects, bank masters, address book, delivery regions, pickup stations, service
  types, tax rates for sales, branding. They belong to projects-api, treasury-api, ordering-backend and
  auth-api.
- Reference data that is the same for every tenant (statutory rates) is seeded once under the system
  tenant; business configuration that differs per tenant is seeded per tenant (`cmd/seed-defaults`).

## Cutover

The service replaced the retired legacy ERP on 2026-08-30 and its one-off data migration tool was
removed in the same change. The production database still holds the retired system's tables in the
`public` schema; the service never reads them (see `backlog.md`).
