package attendance

import (
	"context"
	"fmt"
	"time"

	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/timesheet"
	"github.com/Bengo-Hub/erp-api/internal/ent/timesheetentry"
)

// MaxProjectHoursBatch caps how many projects one ProjectHours call may ask about.
const MaxProjectHoursBatch = 100

// ProjectHours is the time logged against one project: approved hours count for utilisation and
// earned value; submitted hours are waiting for approval.
type ProjectHours struct {
	ProjectID      uuid.UUID       `json:"project_id"`
	ApprovedHours  decimal.Decimal `json:"approved_hours"`
	SubmittedHours decimal.Decimal `json:"submitted_hours"`
}

// ProjectHours sums regular plus overtime hours per project from timesheet entries, split by the
// status of the timesheet they belong to, in two grouped queries. from/to bound the entry date
// (inclusive; zero means open). Projects with no time come back as zero rows, in the order asked.
func (s *Service) ProjectHours(ctx context.Context, tenantID uuid.UUID, projectIDs []uuid.UUID, from, to time.Time) ([]ProjectHours, error) {
	if len(projectIDs) == 0 {
		return []ProjectHours{}, nil
	}
	if len(projectIDs) > MaxProjectHoursBatch {
		return nil, fmt.Errorf("attendance: at most %d projects per call", MaxProjectHoursBatch)
	}
	sum := func(status timesheet.Status) (map[uuid.UUID]decimal.Decimal, error) {
		q := s.orm.TimesheetEntry.Query().
			Where(timesheetentry.TenantID(tenantID), timesheetentry.ProjectIDIn(projectIDs...)).
			Where(func(sel *entsql.Selector) {
				t := entsql.Table(timesheet.Table)
				sel.Where(entsql.In(sel.C(timesheetentry.FieldTimesheetID),
					entsql.Select(t.C(timesheet.FieldID)).From(t).
						Where(entsql.And(entsql.EQ(t.C(timesheet.FieldTenantID), tenantID), entsql.EQ(t.C(timesheet.FieldStatus), status)))))
			})
		if !from.IsZero() {
			q = q.Where(timesheetentry.DateGTE(from))
		}
		if !to.IsZero() {
			q = q.Where(timesheetentry.DateLTE(to))
		}
		var rows []struct {
			ProjectID uuid.UUID       `json:"project_id"`
			Hours     decimal.Decimal `json:"hours"`
		}
		err := q.GroupBy(timesheetentry.FieldProjectID).
			Aggregate(func(sel *entsql.Selector) string {
				return entsql.As(fmt.Sprintf("COALESCE(SUM(COALESCE(%s, 0) + COALESCE(%s, 0)), 0)",
					sel.C(timesheetentry.FieldRegularHours), sel.C(timesheetentry.FieldOvertimeHours)), "hours")
			}).
			Scan(ctx, &rows)
		if err != nil {
			return nil, err
		}
		out := make(map[uuid.UUID]decimal.Decimal, len(rows))
		for _, r := range rows {
			out[r.ProjectID] = r.Hours
		}
		return out, nil
	}
	approved, err := sum(timesheet.StatusApproved)
	if err != nil {
		return nil, fmt.Errorf("attendance: approved project hours: %w", err)
	}
	submitted, err := sum(timesheet.StatusSubmitted)
	if err != nil {
		return nil, fmt.Errorf("attendance: submitted project hours: %w", err)
	}
	out := make([]ProjectHours, 0, len(projectIDs))
	for _, id := range projectIDs {
		out = append(out, ProjectHours{ProjectID: id, ApprovedHours: approved[id], SubmittedHours: submitted[id]})
	}
	return out, nil
}
