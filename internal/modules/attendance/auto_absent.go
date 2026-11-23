package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/publicholiday"
)

// autoAbsentChunk bounds the employee ids sent in one statement.
const autoAbsentChunk = 1000

// autoAbsentSQL inserts an absent record for each listed employee who has no record for the
// day, no approved leave covering it, no off-day on it and had joined by then. An existing
// record (a punch that arrived first, a manual entry) always wins through ON CONFLICT.
const autoAbsentSQL = `
INSERT INTO attendance_records
  (id, tenant_id, employee_id, outlet_id, date, status, total_seconds_worked,
   regular_hours, overtime_hours, metadata, created_at, updated_at)
SELECT gen_random_uuid(), $1, e.id, e.outlet_id, $2, 'absent', 0, 0, 0,
       '{"auto_absent": true, "source": "auto"}'::jsonb, now(), now()
FROM employees e
WHERE e.tenant_id = $1
  AND e.id = ANY($3)
  AND e.deleted = false AND e.terminated = false
  AND NOT EXISTS (
    SELECT 1 FROM leave_requests l
    WHERE l.tenant_id = $1 AND l.employee_id = e.id AND l.status = 'approved'
      AND l.start_date < $4 AND l.end_date >= $2)
  AND NOT EXISTS (
    SELECT 1 FROM off_days o
    WHERE o.tenant_id = $1 AND o.employee_id = e.id AND o.date >= $2 AND o.date < $4)
  AND NOT EXISTS (
    SELECT 1 FROM hr_details h
    WHERE h.tenant_id = $1 AND h.employee_id = e.id AND h.date_joined >= $4)
ON CONFLICT (tenant_id, employee_id, date) DO NOTHING`

// MarkAbsent writes absent records for one tenant and work day: every active employee whose
// planned shift makes the day a working day (overrides, rosters, standard shift, default) and
// who is not on a public holiday (national or their county's), approved leave or an off-day,
// and has no record yet. Returns the rows inserted.
func (s *Service) MarkAbsent(ctx context.Context, tenantID uuid.UUID, day time.Time, st Settings) (int64, error) {
	day = dateOnly(day)
	emps, err := s.orm.Employee.Query().Where(
		employee.TenantID(tenantID), employee.Deleted(false), employee.Terminated(false),
	).IDs(ctx)
	if err != nil {
		return 0, fmt.Errorf("attendance: auto-absent employees: %w", err)
	}
	if len(emps) == 0 {
		return 0, nil
	}
	expected, err := s.expectedToWork(ctx, tenantID, emps, day, st)
	if err != nil {
		return 0, err
	}
	var total int64
	for i := 0; i < len(expected); i += autoAbsentChunk {
		end := i + autoAbsentChunk
		if end > len(expected) {
			end = len(expected)
		}
		res, err := s.orm.ExecContext(ctx, autoAbsentSQL, tenantID, day, expected[i:end], day.AddDate(0, 0, 1))
		if err != nil {
			return total, fmt.Errorf("attendance: auto-absent insert: %w", err)
		}
		if n, rerr := res.RowsAffected(); rerr == nil {
			total += n
		}
	}
	return total, nil
}

// expectedToWork filters employees down to those planned to work on day and not on a public
// holiday that applies to them.
func (s *Service) expectedToWork(ctx context.Context, tenantID uuid.UUID, emps []uuid.UUID, day time.Time, st Settings) ([]uuid.UUID, error) {
	keys := make([]empDay, len(emps))
	for i, id := range emps {
		keys[i] = empDay{id, day}
	}
	shifts, err := s.resolveShifts(ctx, tenantID, keys, st)
	if err != nil {
		return nil, err
	}
	hols, err := s.orm.PublicHoliday.Query().Where(publicholiday.TenantID(tenantID),
		publicholiday.DateGTE(day), publicholiday.DateLT(day.AddDate(0, 0, 1))).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: auto-absent holidays: %w", err)
	}
	national := false
	counties := map[string]bool{}
	for _, h := range hols {
		if h.IsNational {
			national = true
		} else if h.County != nil {
			counties[countyKey(*h.County)] = true
		}
	}
	if national {
		return nil, nil
	}
	var countyOf map[uuid.UUID][]string
	if len(counties) > 0 {
		if countyOf, err = s.employeeCounties(ctx, tenantID, emps); err != nil {
			return nil, err
		}
	}
	return selectExpected(keys, shifts, counties, countyOf), nil
}

// selectExpected keeps the employees with a known working shift that day who are not on one of
// the day's county holidays. Pure, for tests.
func selectExpected(keys []empDay, shifts map[empDay]DayShift, holidayCounties map[string]bool, countyOf map[uuid.UUID][]string) []uuid.UUID {
	out := make([]uuid.UUID, 0, len(keys))
	for _, k := range keys {
		ds, ok := shifts[k]
		if !ok || ds.Off || ds.Source == ShiftFromNone {
			continue
		}
		onHoliday := false
		for _, c := range countyOf[k.Emp] {
			if holidayCounties[c] {
				onHoliday = true
				break
			}
		}
		if !onHoliday {
			out = append(out, k.Emp)
		}
	}
	return out
}

// autoAbsentDay is the local work day the auto-absent job should close for a tenant at now:
// today once the local clock passes the cut-off time, else yesterday (catching up after a
// pause). ok is false when the cut-off time is invalid.
func autoAbsentDay(now time.Time, loc *time.Location, cutoff string) (time.Time, bool) {
	today := localDate(now, loc)
	at, ok := clockOn(today, cutoff, loc)
	if !ok {
		return time.Time{}, false
	}
	if now.Before(at) {
		return today.AddDate(0, 0, -1), true
	}
	return today, true
}
