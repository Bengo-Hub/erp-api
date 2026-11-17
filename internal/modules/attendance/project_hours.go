package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// MaxProjectHoursBatch caps how many projects one ProjectHours call may ask about.
const MaxProjectHoursBatch = 100

// ProjectHours is the time logged against one project: approved hours count for utilisation and
// earned value; submitted hours are waiting for approval. LabourCost is the approved hours priced at
// each employee's hourly rate (zero without salary details); UnbilledBillableHours is the approved,
// billable time no billing run has reserved yet.
type ProjectHours struct {
	ProjectID             uuid.UUID       `json:"project_id"`
	ApprovedHours         decimal.Decimal `json:"approved_hours"`
	SubmittedHours        decimal.Decimal `json:"submitted_hours"`
	LabourCost            decimal.Decimal `json:"labour_cost"`
	UnbilledBillableHours decimal.Decimal `json:"unbilled_billable_hours"`
}

// projectHoursSQL sums regular plus overtime hours per project in one grouped query. The hourly rate
// is each employee's newest salary details row (the active one first), read once per tenant.
const projectHoursSQL = `WITH rate AS (
  SELECT DISTINCT ON (employee_id) employee_id, hourly_rate
  FROM salary_details WHERE tenant_id = $1
  ORDER BY employee_id, is_active DESC, updated_at DESC
)
SELECT e.project_id,
  COALESCE(SUM(COALESCE(e.regular_hours, 0) + COALESCE(e.overtime_hours, 0)) FILTER (WHERE t.status = 'approved'), 0)::text,
  COALESCE(SUM(COALESCE(e.regular_hours, 0) + COALESCE(e.overtime_hours, 0)) FILTER (WHERE t.status = 'submitted'), 0)::text,
  COALESCE(SUM((COALESCE(e.regular_hours, 0) + COALESCE(e.overtime_hours, 0)) * COALESCE(r.hourly_rate, 0)) FILTER (WHERE t.status = 'approved'), 0)::text,
  COALESCE(SUM(COALESCE(e.regular_hours, 0) + COALESCE(e.overtime_hours, 0)) FILTER (
    WHERE t.status = 'approved' AND e.billable AND e.metadata->>'billing_ref' IS NULL), 0)::text
FROM timesheet_entries e
JOIN timesheets t ON t.id = e.timesheet_id AND t.tenant_id = $1
LEFT JOIN rate r ON r.employee_id = t.employee_id
WHERE e.tenant_id = $1 AND e.project_id = ANY($2::uuid[])
  AND t.status IN ('approved', 'submitted')
  AND ($3::timestamptz IS NULL OR e.date >= $3)
  AND ($4::timestamptz IS NULL OR e.date < $4)
GROUP BY e.project_id`

// ProjectHours sums regular plus overtime hours per project from timesheet entries, split by the
// status of the timesheet they belong to, with the approved labour cost and the unbilled billable
// hours, in one grouped query. from/to bound the entry date (inclusive; zero means open). Projects
// with no time come back as zero rows, in the order asked.
func (s *Service) ProjectHours(ctx context.Context, tenantID uuid.UUID, projectIDs []uuid.UUID, from, to time.Time) ([]ProjectHours, error) {
	if len(projectIDs) == 0 {
		return []ProjectHours{}, nil
	}
	if len(projectIDs) > MaxProjectHoursBatch {
		return nil, fmt.Errorf("attendance: at most %d projects per call", MaxProjectHoursBatch)
	}
	ids := make([]string, len(projectIDs))
	for i, id := range projectIDs {
		ids[i] = id.String()
	}
	var lo, hi *time.Time
	if !from.IsZero() {
		lo = &from
	}
	if !to.IsZero() {
		end := to.AddDate(0, 0, 1)
		hi = &end
	}
	rows, err := s.orm.QueryContext(ctx, projectHoursSQL, tenantID, ids, lo, hi)
	if err != nil {
		return nil, fmt.Errorf("attendance: project hours: %w", err)
	}
	defer rows.Close()
	byID := make(map[uuid.UUID]ProjectHours, len(projectIDs))
	for rows.Next() {
		var (
			p                                   ProjectHours
			approved, submitted, cost, unbilled string
		)
		if err := rows.Scan(&p.ProjectID, &approved, &submitted, &cost, &unbilled); err != nil {
			return nil, fmt.Errorf("attendance: scan project hours: %w", err)
		}
		for dst, v := range map[*decimal.Decimal]string{&p.ApprovedHours: approved, &p.SubmittedHours: submitted, &p.LabourCost: cost, &p.UnbilledBillableHours: unbilled} {
			if *dst, err = decimal.NewFromString(v); err != nil {
				return nil, fmt.Errorf("attendance: project hours value: %w", err)
			}
		}
		p.LabourCost = p.LabourCost.Round(2)
		byID[p.ProjectID] = p
	}
	if err := rows.Err(); err != nil {
		return nil, fmt.Errorf("attendance: project hours: %w", err)
	}
	out := make([]ProjectHours, 0, len(projectIDs))
	for _, id := range projectIDs {
		p, ok := byID[id]
		if !ok {
			p = ProjectHours{ProjectID: id}
		}
		out = append(out, p)
	}
	return out, nil
}
