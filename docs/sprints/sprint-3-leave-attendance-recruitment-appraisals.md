# Sprint 3 — Leave, Attendance/Shifts, Recruitment, Training, Appraisals

> The remaining HR domains around payroll. Mostly CRUD + a few engines (leave accrual/balance,
> attendance rules/overtime, shift rotation). All tenant-scoped. Can run in parallel with Sprint 2
> after Sprint 1. References: `erd.md §7-9`, `hrm/{leave,attendance,recruitment,training,appraisals,
> performance}/`, `hrm/leave/management/commands/accrue_leave.py`, `hrm/attendance/shift_planner_*`.

## Goals
- Port the non-payroll HR modules with full tenant isolation and no silent-zero error handling.
- Replace Celery/command-driven jobs (leave accrual, contract expiry) with cron goroutines / NATS.

## Scope

### `modules/leave`
- `LeaveCategory`, `LeaveEntitlement`, `LeaveRequest`, `LeaveBalance`, `LeaveLog`, `PublicHoliday`.
- Balance computation (entitled/taken/remaining), carryover with `max_carryover_days`, approval flow
  (integrate with `modules/approvals` in S4; until then a direct approve/reject).
- **Leave accrual cron** (port `accrue_leave.py`) as a scheduled goroutine / k8s CronJob; tenant-scoped.
- Leave-decision notifications via `erp.notification.requested` (port `_notify_leave_decision`).
- `PublicHoliday` becomes tenant-scoped (currently global; `uniq(date,county)` → `uniq(tenant,date,county)`).

### `modules/attendance`
- `WorkShift`(+`WorkShiftSchedule`), `AttendanceRecord`, `AttendanceRule`, `ShiftRotation`, `OffDay`,
  `ESSSettings` (per-tenant, not singleton), `Timesheet`(+`TimesheetEntry`), shift planner
  (`ShiftRoster`/`Slot`/`Assignment`/`StaffShiftOverride` — port `shift_planner_models.py`/`_api.py`).
- Overtime/late/absence computation from `AttendanceRule` (priority-ordered); `decimal` hours.
- Replace `DefaultShiftMiddleware` (per-request "ensure Regular shift") with a one-time seed per tenant
  (fixes `gaps-and-bugs.md §5` per-request ensure anti-pattern).
- GPS/biometric fields preserved; attendance status enum (`present|absent|late|half-day`).

### `modules/recruitment`
- `JobPosting`, `Candidate`, `Application` (status FSM: applied→screening→interview→offered→hired→rejected),
  `EmployeeOnboarding`(+`OnboardingTask`) — port `onboarding_models.py`/`onboarding_api.py`.
- On `hired`, optionally create an `Employee` (link to onboarding) — keep tenant-scoped.

### `modules/training`
- `TrainingCourse`, `TrainingEnrollment` (`uniq(course,employee)`), `TrainingEvaluation`.

### `modules/appraisals` + `modules/performance`
- `AppraisalCycle`/`Template`/`Question`/`Appraisal`/`Response`, `Goal`(+`GoalProgress`).
- `MetricCategory`, `PerformanceMetric`, `EmployeeMetric`, `MetricTarget`, `PerformanceReview`(+`ReviewMetric`).
- Ratings as `decimal` (0-5); review FSM.

## Endpoints
- `/api/v1/hrm/leave/{categories,entitlements,requests,balances,holidays}/...`
- `/api/v1/hrm/attendance/{shifts,records,rules,rotations,timesheets,rosters,ess-settings}/...`
- `/api/v1/hrm/recruitment/{postings,candidates,applications,onboarding}/...`
- `/api/v1/hrm/training/{courses,enrollments,evaluations}/...`
- `/api/v1/hrm/appraisals/...`, `/api/v1/hrm/performance/...`

## Ent schemas
All entities above with `tenant_id` + composite `(tenant_id, …)` indexes; per-tenant settings
(`ESSSettings`, leave config) replacing Django singletons.

## Events
- OUT: `erp.notification.requested` (leave decisions, onboarding tasks, training reminders),
  `erp.email.requested` where applicable. No new external contracts.

## Acceptance criteria
- Tenant isolation enforced on every list/retrieve/mutate (automated cross-tenant test).
- Leave balance math correct across entitlement + taken + carryover; accrual cron runs and is idempotent.
- Attendance overtime/late computed per rule priority; hours are `decimal`.
- No per-request "ensure default exists" — defaults seeded once per tenant.
- Application/onboarding/review FSMs reject invalid transitions.

## Dependencies
- Sprint 1 (rails). Soft dependency on Sprint 4 for the shared approval engine (use direct
  approve/reject until S4 lands, then route leave/appraisal/contract approvals through it).

---

## Status: Done (re-verified on `main` 2026-09-27)

The RBAC seed and resume upload from the deferred list below shipped in Sprint 4, and leave and appraisals now use the shared approval engine. Still open: attendance penalty deductions are not applied to payslips (`docs/backlog.md`).

All five domains implemented in Go, tenant-scoped, RBAC-enforced, building green
(`go build ./...` + `go vet ./...`). Endpoints under `/api/v1/hrm/...`, all `data`-enveloped.

**Modules / Ent schemas (all tenant_id + composite indexes; decimal for days/hours/ratings):**
- `modules/leave` — LeaveCategory, LeaveEntitlement, LeaveRequest (FSM
  pending→approved|rejected|cancelled), LeaveBalance, LeaveLog, PublicHoliday
  (now tenant-scoped `uniq(tenant,date,county)`). Balance math (entitled/taken/remaining)
  kept in sync on entitlement upsert, approve (deduct), cancel-of-approved (return).
  Idempotent accrual with capped carryover (port of `accrue_leave.py`); in-process accrual
  cron goroutine (`LEAVE_ACCRUAL_INTERVAL`, default 24h) + per-tenant `POST /leave/accrue`.
  Leave decisions emit `erp.notification.requested` via the outbox.
- `modules/attendance` — WorkShift(+Schedule, `is_default` seed flag), AttendanceRecord
  (GPS/biometric, status `present|absent|late|half-day`), AttendanceRule (priority-ordered
  policies), ShiftRotation, OffDay, ESSSettings (**per-tenant, not singleton**),
  Timesheet(+Entry, FSM, totals rollup), shift planner (ShiftRoster/Slot/Assignment,
  StaffShiftOverride). Late-detection + overtime/half-day split as a pure decimal package
  (port of `apply_late_status`/`compute_hours`); highest-priority active `overtime_policy`
  drives the split. `EnsureDefaultShift` seeds one Regular shift per tenant (replaces the
  per-request `DefaultShiftMiddleware`, gaps §5).
- `modules/recruitment` — JobPosting, Candidate, Application (hiring FSM
  applied→screening→interview→offered→hired; rejected from any non-terminal),
  EmployeeOnboarding(+OnboardingTask). On hire (`create_employee=true`) atomically creates an
  Employee from the candidate, seeds the 10-item IT/HR/Training checklist, links
  `hired_employee_id`. Task completion auto-completes onboarding.
- `modules/training` — TrainingCourse, TrainingEnrollment (`uniq(tenant,course,employee)` +
  capacity enforcement), TrainingEvaluation (rating clamped 0-5).
- `modules/appraisals` — AppraisalCycle (FSM), AppraisalTemplate/Question, Appraisal (FSM
  draft→in_progress→completed→approved|rejected) + AppraisalResponse, Goal(+GoalProgress,
  progress 0-100 syncs goal status). Ratings decimal 0-5.
- `modules/performance` — MetricCategory, PerformanceMetric, EmployeeMetric (numeric
  projection per type), MetricTarget, PerformanceReview (FSM) + ReviewMetric. Ratings/values
  decimal.

**Atlas migrations (apply clean on a fresh schema, verified):**
`20260614165124_leave_schema`, `20260614170337_attendance_schema`,
`20260614201329_recruitment_schema`, `20260614202321_training_appraisals_performance_schema`.

**Acceptance criteria met:** tenant_id on every business table + tenant-filtered handlers;
leave balance math + idempotent accrual cron; decimal hours/overtime per rule priority;
defaults seeded once per tenant (no per-request ensure); application/onboarding/timesheet/
appraisal/review FSMs reject invalid transitions.

**Deferred / notes:**
- Leave/appraisal approvals use direct approve/reject (per spec) until the Sprint 4 shared
  approval engine lands.
- RBAC permission codes (`hrm.{leave,attendance,recruitment,training,appraisal,performance}.
  {view,manage,approve}`) are enforced by handlers; seeding them into roles is a `cmd/seed`
  follow-up (Sprint 4 config work). Platform owners/superusers/services bypass.
- Candidate resume upload stores a relative media path only (no file-upload endpoint yet) —
  follows the per-tenant media convention; wiring the upload is a later task.
- AttendanceRule late/absenteeism *penalty enforcement* (salary deduction wiring into
  payroll) is modeled but not yet applied to payslips — payroll integration is a follow-up.
