# ERP API Backlog

**Last updated:** 2026-09-27. Built by checking `docs/revamp-plan.md`, `docs/sprints/*.md` and `docs/integrations.md` against the code on `main`. Each item names the doc it came from. Items marked **In progress (plan budgets-planning-projects-bi-2026-09-27)** are being built now under `.claude/plans/budgets-planning-projects-bi-2026-09-27.md`; do not start them separately. UI gaps live in `erp/erp-ui/docs/backlog.md`.

## Analytics and reports

- New `/hrm/analytics` endpoint, SQL grouped: headcount by department, gender and type; hires, exits and turnover; contracts expiring in 30, 60 and 90 days; payroll cost trend by month, department and project; overtime; leave liability. In progress (plan budgets-planning-projects-bi-2026-09-27). Source: erp-ui sprint-4 (dashboards), revamp-plan.md.
- Rewrite `HeadcountSummary`, `PayrollSummary` and `employeeMap` as grouped SQL; reports aggregate in Go memory today (`reports/service.go`, `summaries.go`). In progress (plan budgets-planning-projects-bi-2026-09-27). Source: sprint-4 status.
- Timesheet summary S2S endpoint for projects utilisation (`/s2s/{tenant}/timesheets/summary`). In progress (plan budgets-planning-projects-bi-2026-09-27). Source: budgets plan Phase 3.

## Payroll and cost dimensions

- `erp.payroll.processed` hardcodes `"cost_center": ""` (`payroll/event_payload.go`). In progress (plan budgets-planning-projects-bi-2026-09-27). Source: integrations.md.
- Split payroll cost per `EmployeeProjectAllocation` into `allocations[]` on the payroll event, with the remainder on the department cost center. In progress (plan budgets-planning-projects-bi-2026-09-27). Source: sprint-2 status, integrations.md.
- Department cost center link in `Department.metadata.cost_center_id`. In progress (plan budgets-planning-projects-bi-2026-09-27). Source: budgets plan Phase 2.
- Publish `erp.expense_claim.submitted` and `.rejected` so treasury can track claim commitments. In progress (plan budgets-planning-projects-bi-2026-09-27). Source: integrations.md.
- Claim approval budget check against treasury `/s2s/{tenant}/budgets/check`. In progress (plan budgets-planning-projects-bi-2026-09-27). Source: budgets plan Phase 1.
- Apply attendance late and absence penalties to payslips (modelled, not applied). Source: sprint-3 deferred notes.
- Realtime payroll progress socket for erp-ui. Source: erp-ui sprint-2 and sprint-5.

## Platform

- Projects lookup client (`platform/lookups/client.go`) sends no `X-Tenant-ID`, so it always falls back to an unbounded scan in `lookups_fallback.go`. In progress (plan budgets-planning-projects-bi-2026-09-27, Phase 0). Source: sprint-4 status.
