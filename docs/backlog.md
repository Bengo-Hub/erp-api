# ERP API Backlog

**Last updated:** 2026-10-16. Built by checking `docs/revamp-plan.md`, `docs/sprints/*.md` and `docs/integrations.md` against the code on `main`. Each item names the doc it came from. The budgets, planning, project costing and BI plan (`.claude/plans/budgets-planning-projects-bi-2026-09-27.md`) is complete for ERP; its items are listed under Done. UI gaps live in `erp/erp-ui/docs/backlog.md`.

## Open

- Calculation preview (`POST /hrm/payroll/calculation-preview`) still runs inside the request. Since the run inputs are batched it costs a few grouped reads plus pure computation, so it fits the 20s write timeout for normal payrolls; move it to the background job too if a tenant with several thousand employees hits the limit. Source: 2026-10-16 review.
- Per-employee writes in a persisted run (payslip upsert, payslip lines, recovery lines, attendance applied) are still one small batch per employee; acceptable now the run is a background job. Source: 2026-10-16 review.

## Done (2026-10-15 and 2026-10-16)

- Payroll run inputs are loaded once per run (`loadRunInputs`, IN chunks of 1000) instead of seven or more queries per employee; the newest active salary row wins deterministically. Commit `1be3792`.

- Attendance penalties reach payslips after review. `AttendanceDeduction` rows per employee, month and kind are computed from attendance records, the most specific active late, absenteeism and work-hours rules (department, then branch, then tenant-wide) and approved leave: late `fixed` per arrival, `percent_daily` of the daily rate, `per_minute` at the minute rate, `warning` nothing; unexcused absence at the daily rate unless the absenteeism action is not a deduction. Daily rate is salary over the month's weekdays. Minutes late are measured in the shift outlet's time zone (else the company's, else Africa/Nairobi). HR approves, waives or reopens rows (`/hrm/payroll/attendance-deductions`, `/compute`, `/review`); the run takes approved amounts off gross before statutory deductions and PAYE, writes negative earning lines and marks the rows applied. Commit `f80e34f`. Source: sprint-3 deferred notes.
- Payroll runs in the background with live progress. `process-with-formulas` answers 202 with a `PayrollRunJob`; one active run per tenant across pods (unique `(tenant_id, active_lock)`, 409 `run_in_progress`); progress at most once a second plus a 15s heartbeat; `GET /hrm/payroll/runs`, `/runs/{id}`, `/runs/{id}/events` (Server-Sent Events in 15s windows inside the router and write timeouts); `task_status?task_id=` reports the real run. Runs stop with the server and are recorded as interrupted, and a sweeper on every pod marks stale runs. Commit `0a6350d`. This replaces the planned WebSocket. Source: erp-ui sprint-2 and sprint-5.

## Done (plan budgets-planning-projects-bi-2026-09-27)

### Analytics and reports

- `GET /reports/hrm-analytics`, all grouped in SQL: headcount by department, gender and employment type; new hires; exits and turnover (from `Employee.terminated_at`, set on terminate and cleared on reinstate); contracts expiring in 30, 60 and 90 days; 12-month payroll trend; payroll by department; overtime (attendance and timesheets reported apart); leave liability. Commits `f24a522`, `b8fedb5`.
- `HeadcountSummary` grouped in SQL; statutory reports load only the employees on the month's payslips (chunked IN) instead of every employee ever. Commits `f24a522`, `a7f0c80`.
- `GET /hrm/attendance/timesheets/project-hours`: approved and submitted timesheet hours per project, grouped, read by projects-api for utilisation. Commit `786ef39`.
- `GET /hrm/payroll/labour-cost?month=YYYY-MM`: a payroll month's gross pay by project, split with the same allocation rules (`costAllocations`) the payroll event posts to treasury, so the figures match project costs there. Commit `bb49507`.

### Payroll and cost dimensions

- `erp.payroll.processed` carries the real cost centre and `allocations[]` per employee from `EmployeeProjectAllocation` (fixed first, then percent, capped; the rest on the department cost centre). Commit `0f794f2`.
- `Department.cost_center_id`, editable through the API and the erp-ui department form. Commit `0f794f2`.
- `erp.expense_claim.created|updated|deleted` (one claim payload for every claim event) so treasury tracks claim commitments. Commit `da7c1f0`.
- Claim approval runs treasury's `POST /s2s/{tenant}/budgets/claim-check`. A stop answers 409 `over_budget`; holders of `approvals.decide` can approve with the override. Commit `b8fedb5`.

### Platform

- Projects lookup client sends `X-Tenant-ID`; the fallback is a bounded `SELECT DISTINCT ... LIMIT`. Commit `0f794f2`.
