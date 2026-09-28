# ERP API Backlog

**Last updated:** 2026-09-28. Built by checking `docs/revamp-plan.md`, `docs/sprints/*.md` and `docs/integrations.md` against the code on `main`. Each item names the doc it came from. The budgets, planning, project costing and BI plan (`.claude/plans/budgets-planning-projects-bi-2026-09-27.md`) is complete for ERP; its items are listed under Done. UI gaps live in `erp/erp-ui/docs/backlog.md`.

## Open

- Apply attendance late and absence penalties to payslips (modelled, not applied). Source: sprint-3 deferred notes.
- Realtime payroll progress socket for erp-ui. Source: erp-ui sprint-2 and sprint-5.

## Done (plan budgets-planning-projects-bi-2026-09-27)

### Analytics and reports

- `GET /reports/hrm-analytics`, all grouped in SQL: headcount by department, gender and employment type; new hires; exits and turnover (from `Employee.terminated_at`, set on terminate and cleared on reinstate); contracts expiring in 30, 60 and 90 days; 12-month payroll trend; payroll by department; overtime (attendance and timesheets reported apart); leave liability. Commits `4040b96`, `2685c76`.
- `HeadcountSummary` grouped in SQL; statutory reports load only the employees on the month's payslips (chunked IN) instead of every employee ever. Commits `4040b96`, `ec83e67`.
- `GET /hrm/attendance/timesheets/project-hours`: approved and submitted timesheet hours per project, grouped, read by projects-api for utilisation. Commit `44dfc89`.
- `GET /hrm/payroll/labour-cost?month=YYYY-MM`: a payroll month's gross pay by project, split with the same allocation rules (`costAllocations`) the payroll event posts to treasury, so the figures match project costs there. Commit `4b1613e`.

### Payroll and cost dimensions

- `erp.payroll.processed` carries the real cost centre and `allocations[]` per employee from `EmployeeProjectAllocation` (fixed first, then percent, capped; the rest on the department cost centre). Commit `7c3fcd3`.
- `Department.cost_center_id`, editable through the API and the erp-ui department form. Commit `7c3fcd3`.
- `erp.expense_claim.created|updated|deleted` (one claim payload for every claim event) so treasury tracks claim commitments. Commit `64fb303`.
- Claim approval runs treasury's `POST /s2s/{tenant}/budgets/claim-check`. A stop answers 409 `over_budget`; holders of `approvals.decide` can approve with the override. Commit `2685c76`.

### Platform

- Projects lookup client sends `X-Tenant-ID`; the fallback is a bounded `SELECT DISTINCT ... LIMIT`. Commit `7c3fcd3`.
