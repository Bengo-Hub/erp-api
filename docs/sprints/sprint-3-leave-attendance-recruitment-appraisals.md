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
