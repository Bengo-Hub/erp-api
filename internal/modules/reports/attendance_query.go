package reports

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
)

// Attendance reports run grouped SQL over a bounded date range and return the same
// {report, columns, rows, totals} envelope as the payroll reports.

// MaxAttendanceRangeDays bounds every attendance report.
const MaxAttendanceRangeDays = 366

// maxReportRows caps row-level attendance reports (register, early leave, access log).
const maxReportRows = 20000

// AttendanceFilter is the shared filter for attendance reports: a date range plus optional
// department, outlet and employee.
type AttendanceFilter struct {
	From, To     time.Time // inclusive days, UTC midnight
	DepartmentID *uuid.UUID
	OutletID     *uuid.UUID
	EmployeeID   *uuid.UUID
}

// NewAttendanceFilter validates and bounds a range: To defaults to today, From to the first of
// To's month, and the span is at most MaxAttendanceRangeDays.
func NewAttendanceFilter(from, to *time.Time, dept, outlet, emp *uuid.UUID) (AttendanceFilter, error) {
	day := func(t time.Time) time.Time {
		y, m, d := t.UTC().Date()
		return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
	}
	f := AttendanceFilter{To: day(time.Now()), DepartmentID: dept, OutletID: outlet, EmployeeID: emp}
	if to != nil {
		f.To = day(*to)
	}
	f.From = time.Date(f.To.Year(), f.To.Month(), 1, 0, 0, 0, 0, time.UTC)
	if from != nil {
		f.From = day(*from)
	}
	if f.To.Before(f.From) {
		return f, errors.New("to must not be before from")
	}
	if f.To.Sub(f.From) > MaxAttendanceRangeDays*24*time.Hour {
		return f, fmt.Errorf("the range may cover at most %d days", MaxAttendanceRangeDays)
	}
	return f, nil
}

func (f AttendanceFilter) meta() PeriodMeta {
	return PeriodMeta{Start: f.From.Format("2006-01-02"), End: f.To.Format("2006-01-02")}
}

// sqlArgs collects positional arguments; $1 is always the tenant.
type sqlArgs struct{ list []any }

func (a *sqlArgs) add(v any) string {
	a.list = append(a.list, v)
	return fmt.Sprintf("$%d", len(a.list))
}

// employeeScope is the WHERE clause for employees aliased e, honouring the filter.
func (f AttendanceFilter) employeeScope(a *sqlArgs) string {
	parts := []string{"e.tenant_id = $1", "e.deleted = false"}
	if f.OutletID != nil {
		parts = append(parts, "e.outlet_id = "+a.add(*f.OutletID))
	}
	if f.EmployeeID != nil {
		parts = append(parts, "e.id = "+a.add(*f.EmployeeID))
	}
	if f.DepartmentID != nil {
		parts = append(parts, "EXISTS (SELECT 1 FROM hr_details hd WHERE hd.tenant_id = $1 AND hd.employee_id = e.id AND hd.department_id = "+a.add(*f.DepartmentID)+")")
	}
	return strings.Join(parts, " AND ")
}

// SQL fragments shared by the attendance reports.
const (
	empNameSQL = `TRIM(COALESCE(e.first_name, '') || ' ' || COALESCE(e.last_name, ''))`
	// deptJoinSQL adds dep.title: the employee's department (latest HR details row).
	deptJoinSQL = `LEFT JOIN LATERAL (
  SELECT dpt.title FROM hr_details h JOIN departments dpt ON dpt.id = h.department_id
  WHERE h.tenant_id = e.tenant_id AND h.employee_id = e.id
  ORDER BY h.updated_at DESC LIMIT 1) dep ON true`
	lateMinutesSQL  = `COALESCE((r.metadata->>'late_minutes')::int, 0)`
	earlyMinutesSQL = `COALESCE((r.metadata->>'early_leave_minutes')::int, 0)`
	isoSQL          = `to_char(%s AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"')`
	daySQL          = `to_char(%s AT TIME ZONE 'UTC', 'YYYY-MM-DD')`
)

// queryMaps runs a query and returns each row as a map keyed by column name. Byte slices
// (text from the driver) become strings.
func (s *Service) queryMaps(ctx context.Context, query string, args ...any) ([]map[string]any, error) {
	rows, err := s.orm.QueryContext(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer func() { _ = rows.Close() }()
	cols, err := rows.Columns()
	if err != nil {
		return nil, err
	}
	out := []map[string]any{}
	for rows.Next() {
		vals := make([]any, len(cols))
		ptrs := make([]any, len(cols))
		for i := range vals {
			ptrs[i] = &vals[i]
		}
		if err := rows.Scan(ptrs...); err != nil {
			return nil, err
		}
		m := make(map[string]any, len(cols))
		for i, c := range cols {
			if b, ok := vals[i].([]byte); ok {
				m[c] = string(b)
			} else {
				m[c] = vals[i]
			}
		}
		out = append(out, m)
	}
	return out, rows.Err()
}

// sumCols totals numeric columns of the rows.
func sumCols(rows []map[string]any, cols ...string) map[string]any {
	out := map[string]any{}
	for _, c := range cols {
		var t float64
		for _, r := range rows {
			switch v := r[c].(type) {
			case float64:
				t += v
			case int64:
				t += float64(v)
			case int32:
				t += float64(v)
			}
		}
		out[c] = roundTo(t, 2)
	}
	return out
}

func roundTo(v float64, places int) float64 {
	p := 1.0
	for i := 0; i < places; i++ {
		p *= 10
	}
	if v < 0 {
		return -float64(int64(-v*p+0.5)) / p
	}
	return float64(int64(v*p+0.5)) / p
}
