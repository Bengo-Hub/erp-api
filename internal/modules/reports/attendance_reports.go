package reports

import (
	"context"
	"fmt"

	"github.com/google/uuid"
)

// AttendanceRegister lists every attendance record in the range: one row per employee day.
func (s *Service) AttendanceRegister(ctx context.Context, tenantID uuid.UUID, f AttendanceFilter) (*Report, error) {
	a := &sqlArgs{list: []any{tenantID}}
	from, to := a.add(f.From), a.add(f.To.AddDate(0, 0, 1))
	q := fmt.Sprintf(`
SELECT COALESCE(e.employee_number, '') AS employee_number, %s AS employee_name,
       COALESCE(dep.title, '') AS department_name, %s AS date,
       %s AS check_in, %s AS check_out,
       round(r.total_seconds_worked / 3600.0, 2)::float8 AS hours_worked,
       %s AS late_minutes, r.overtime_hours::float8 AS overtime_hours, r.status
FROM attendance_records r
JOIN employees e ON e.id = r.employee_id
%s
WHERE r.tenant_id = $1 AND r.date >= %s AND r.date < %s AND %s
ORDER BY r.date, employee_name
LIMIT %d`, empNameSQL, fmt.Sprintf(daySQL, "r.date"), fmt.Sprintf(isoSQL, "r.check_in"), fmt.Sprintf(isoSQL, "r.check_out"),
		lateMinutesSQL, deptJoinSQL, from, to, f.employeeScope(a), maxReportRows)
	rows, err := s.queryMaps(ctx, q, a.list...)
	if err != nil {
		return nil, fmt.Errorf("attendance register: %w", err)
	}
	return &Report{Report: "attendance-register", Period: f.meta(),
		Columns: []string{"employee_number", "employee_name", "department_name", "date", "check_in", "check_out", "hours_worked", "late_minutes", "overtime_hours", "status"},
		Rows:    rows, Totals: sumCols(rows, "hours_worked", "late_minutes", "overtime_hours")}, nil
}

// Absenteeism gives each employee's present, absent and leave days and the absence rate.
// Working days are the days with a record (present, late, half-day or absent) plus leave days.
func (s *Service) Absenteeism(ctx context.Context, tenantID uuid.UUID, f AttendanceFilter) (*Report, error) {
	a := &sqlArgs{list: []any{tenantID}}
	from, to := a.add(f.From), a.add(f.To.AddDate(0, 0, 1))
	q := fmt.Sprintf(`
WITH att AS (
  SELECT r.employee_id,
         count(*) FILTER (WHERE r.status <> 'absent') AS present,
         count(*) FILTER (WHERE r.status = 'absent') AS absent
  FROM attendance_records r
  WHERE r.tenant_id = $1 AND r.date >= %[1]s AND r.date < %[2]s
  GROUP BY r.employee_id),
lv AS (
  SELECT l.employee_id,
         sum(GREATEST(0, (LEAST(l.end_date, %[2]s::timestamptz - interval '1 day')::date - GREATEST(l.start_date, %[1]s::timestamptz)::date) + 1)) AS leave_days
  FROM leave_requests l
  WHERE l.tenant_id = $1 AND l.status = 'approved' AND l.start_date < %[2]s AND l.end_date >= %[1]s
  GROUP BY l.employee_id)
SELECT COALESCE(e.employee_number, '') AS employee_number, %[3]s AS employee_name,
       COALESCE(dep.title, '') AS department_name,
       (COALESCE(att.present, 0) + COALESCE(att.absent, 0) + COALESCE(lv.leave_days, 0))::bigint AS working_days,
       COALESCE(att.present, 0)::bigint AS days_present, COALESCE(att.absent, 0)::bigint AS days_absent,
       COALESCE(lv.leave_days, 0)::bigint AS days_on_leave,
       CASE WHEN COALESCE(att.present, 0) + COALESCE(att.absent, 0) + COALESCE(lv.leave_days, 0) = 0 THEN 0
            ELSE round(100.0 * COALESCE(att.absent, 0) / (COALESCE(att.present, 0) + COALESCE(att.absent, 0) + COALESCE(lv.leave_days, 0)), 2) END::float8 AS absence_rate
FROM employees e
%[4]s
LEFT JOIN att ON att.employee_id = e.id
LEFT JOIN lv ON lv.employee_id = e.id
WHERE %[5]s AND (att.employee_id IS NOT NULL OR lv.employee_id IS NOT NULL)
ORDER BY absence_rate DESC, employee_name`, from, to, empNameSQL, deptJoinSQL, f.employeeScope(a))
	rows, err := s.queryMaps(ctx, q, a.list...)
	if err != nil {
		return nil, fmt.Errorf("absenteeism: %w", err)
	}
	return &Report{Report: "absenteeism", Period: f.meta(),
		Columns: []string{"employee_number", "employee_name", "department_name", "working_days", "days_present", "days_absent", "days_on_leave", "absence_rate"},
		Rows:    rows, Totals: sumCols(rows, "working_days", "days_present", "days_absent", "days_on_leave")}, nil
}

// Lateness gives each late employee's late days, total and average late minutes.
func (s *Service) Lateness(ctx context.Context, tenantID uuid.UUID, f AttendanceFilter) (*Report, error) {
	a := &sqlArgs{list: []any{tenantID}}
	from, to := a.add(f.From), a.add(f.To.AddDate(0, 0, 1))
	q := fmt.Sprintf(`
SELECT %s AS employee_name, COALESCE(dep.title, '') AS department_name,
       count(*)::bigint AS late_days, sum(%[2]s)::bigint AS late_minutes_total,
       round(avg(%[2]s), 1)::float8 AS average_late_minutes
FROM attendance_records r
JOIN employees e ON e.id = r.employee_id
%[3]s
WHERE r.tenant_id = $1 AND r.date >= %[4]s AND r.date < %[5]s AND %[6]s
  AND (r.status = 'late' OR %[2]s > 0)
GROUP BY e.id, e.first_name, e.last_name, dep.title
ORDER BY late_minutes_total DESC`, empNameSQL, lateMinutesSQL, deptJoinSQL, from, to, f.employeeScope(a))
	rows, err := s.queryMaps(ctx, q, a.list...)
	if err != nil {
		return nil, fmt.Errorf("lateness: %w", err)
	}
	return &Report{Report: "lateness", Period: f.meta(),
		Columns: []string{"employee_name", "department_name", "late_days", "late_minutes_total", "average_late_minutes"},
		Rows:    rows, Totals: sumCols(rows, "late_days", "late_minutes_total")}, nil
}

// EarlyLeave lists the days an employee left before the shift end beyond the grace.
func (s *Service) EarlyLeave(ctx context.Context, tenantID uuid.UUID, f AttendanceFilter) (*Report, error) {
	a := &sqlArgs{list: []any{tenantID}}
	from, to := a.add(f.From), a.add(f.To.AddDate(0, 0, 1))
	q := fmt.Sprintf(`
SELECT %s AS employee_name, COALESCE(dep.title, '') AS department_name, %s AS date,
       COALESCE(r.metadata->>'shift_end', '') AS shift_end, %s AS check_out,
       %s::bigint AS minutes_early
FROM attendance_records r
JOIN employees e ON e.id = r.employee_id
%s
WHERE r.tenant_id = $1 AND r.date >= %s AND r.date < %s AND %s AND %s > 0
ORDER BY r.date, employee_name
LIMIT %d`, empNameSQL, fmt.Sprintf(daySQL, "r.date"), fmt.Sprintf(isoSQL, "r.check_out"), earlyMinutesSQL,
		deptJoinSQL, from, to, f.employeeScope(a), earlyMinutesSQL, maxReportRows)
	rows, err := s.queryMaps(ctx, q, a.list...)
	if err != nil {
		return nil, fmt.Errorf("early leave: %w", err)
	}
	return &Report{Report: "early-leave", Period: f.meta(),
		Columns: []string{"employee_name", "department_name", "date", "shift_end", "check_out", "minutes_early"},
		Rows:    rows, Totals: sumCols(rows, "minutes_early")}, nil
}

// Overtime lists days with overtime and how much of it was approved through overtime requests.
func (s *Service) Overtime(ctx context.Context, tenantID uuid.UUID, f AttendanceFilter) (*Report, error) {
	a := &sqlArgs{list: []any{tenantID}}
	from, to := a.add(f.From), a.add(f.To.AddDate(0, 0, 1))
	q := fmt.Sprintf(`
WITH appr AS (
  SELECT o.employee_id, o.date, sum(o.hours) AS hours,
         bool_or(o.status = 'pending') AS has_pending
  FROM overtime_requests o
  WHERE o.tenant_id = $1 AND o.date >= %[1]s AND o.date < %[2]s AND o.status IN ('approved', 'pending')
  GROUP BY o.employee_id, o.date)
SELECT %[3]s AS employee_name, COALESCE(dep.title, '') AS department_name, %[4]s AS date,
       round(r.total_seconds_worked / 3600.0, 2)::float8 AS hours_worked, r.overtime_hours::float8 AS overtime_hours,
       COALESCE((SELECT sum(o2.hours) FROM overtime_requests o2 WHERE o2.tenant_id = $1 AND o2.employee_id = r.employee_id
                 AND o2.date = r.date AND o2.status = 'approved'), 0)::float8 AS approved_hours,
       CASE WHEN appr.employee_id IS NULL THEN 'not_requested'
            WHEN appr.has_pending THEN 'pending'
            ELSE 'approved' END AS status
FROM attendance_records r
JOIN employees e ON e.id = r.employee_id
%[5]s
LEFT JOIN appr ON appr.employee_id = r.employee_id AND appr.date = r.date
WHERE r.tenant_id = $1 AND r.date >= %[1]s AND r.date < %[2]s AND %[6]s AND r.overtime_hours > 0
ORDER BY r.date, employee_name
LIMIT %[7]d`, from, to, empNameSQL, fmt.Sprintf(daySQL, "r.date"), deptJoinSQL, f.employeeScope(a), maxReportRows)
	rows, err := s.queryMaps(ctx, q, a.list...)
	if err != nil {
		return nil, fmt.Errorf("overtime: %w", err)
	}
	return &Report{Report: "overtime", Period: f.meta(),
		Columns: []string{"employee_name", "department_name", "date", "hours_worked", "overtime_hours", "approved_hours", "status"},
		Rows:    rows, Totals: sumCols(rows, "hours_worked", "overtime_hours", "approved_hours")}, nil
}

// PieceOutputReport sums approved and paid output per employee and piece rate.
func (s *Service) PieceOutputReport(ctx context.Context, tenantID uuid.UUID, f AttendanceFilter) (*Report, error) {
	a := &sqlArgs{list: []any{tenantID}}
	from, to := a.add(f.From), a.add(f.To.AddDate(0, 0, 1))
	q := fmt.Sprintf(`
SELECT %s AS employee_name, COALESCE(dep.title, '') AS department_name, pr.name AS piece_rate_name, pr.unit,
       sum(o.quantity)::float8 AS quantity, sum(o.rejected_quantity)::float8 AS rejected_quantity,
       sum(GREATEST(o.quantity - o.rejected_quantity, 0))::float8 AS paid_quantity,
       CASE WHEN sum(o.quantity) = 0 THEN 0 ELSE round(100 * sum(o.rejected_quantity) / sum(o.quantity), 2) END::float8 AS reject_rate,
       sum(o.amount)::float8 AS amount
FROM piece_outputs o
JOIN employees e ON e.id = o.employee_id
JOIN piece_rates pr ON pr.id = o.piece_rate_id
%s
WHERE o.tenant_id = $1 AND o.date >= %s AND o.date < %s AND o.status IN ('approved', 'paid') AND %s
GROUP BY e.id, e.first_name, e.last_name, dep.title, pr.id, pr.name, pr.unit
ORDER BY employee_name, piece_rate_name`, empNameSQL, deptJoinSQL, from, to, f.employeeScope(a))
	rows, err := s.queryMaps(ctx, q, a.list...)
	if err != nil {
		return nil, fmt.Errorf("piece output: %w", err)
	}
	return &Report{Report: "piece-output", Period: f.meta(),
		Columns: []string{"employee_name", "department_name", "piece_rate_name", "unit", "quantity", "rejected_quantity", "paid_quantity", "reject_rate", "amount"},
		Rows:    rows, Totals: sumCols(rows, "quantity", "rejected_quantity", "paid_quantity", "amount")}, nil
}

// AttendanceSummary is the management view per department: headcount, present, absent and
// late days, attendance rate, overtime hours and piece pay.
func (s *Service) AttendanceSummary(ctx context.Context, tenantID uuid.UUID, f AttendanceFilter) (*Report, error) {
	a := &sqlArgs{list: []any{tenantID}}
	from, to := a.add(f.From), a.add(f.To.AddDate(0, 0, 1))
	q := fmt.Sprintf(`
WITH emp AS (
  SELECT e.id, COALESCE(dep.title, 'No department') AS department_name
  FROM employees e
  %[1]s
  WHERE %[2]s AND e.terminated = false),
att AS (
  SELECT r.employee_id,
         count(*) FILTER (WHERE r.status <> 'absent') AS present,
         count(*) FILTER (WHERE r.status = 'absent') AS absent,
         count(*) FILTER (WHERE r.status = 'late' OR %[5]s > 0) AS late,
         sum(r.overtime_hours) AS ot
  FROM attendance_records r
  WHERE r.tenant_id = $1 AND r.date >= %[3]s AND r.date < %[4]s
  GROUP BY r.employee_id),
pc AS (
  SELECT o.employee_id, sum(o.amount) AS amount
  FROM piece_outputs o
  WHERE o.tenant_id = $1 AND o.date >= %[3]s AND o.date < %[4]s AND o.status IN ('approved', 'paid')
  GROUP BY o.employee_id)
SELECT emp.department_name, count(*)::bigint AS headcount,
       COALESCE(sum(att.present), 0)::bigint AS present_days, COALESCE(sum(att.absent), 0)::bigint AS absent_days,
       COALESCE(sum(att.late), 0)::bigint AS late_days,
       CASE WHEN COALESCE(sum(att.present), 0) + COALESCE(sum(att.absent), 0) = 0 THEN 0
            ELSE round(100.0 * sum(att.present) / (sum(att.present) + sum(att.absent)), 2) END::float8 AS attendance_rate,
       COALESCE(sum(att.ot), 0)::float8 AS overtime_hours, COALESCE(sum(pc.amount), 0)::float8 AS piece_amount
FROM emp
LEFT JOIN att ON att.employee_id = emp.id
LEFT JOIN pc ON pc.employee_id = emp.id
GROUP BY emp.department_name
ORDER BY emp.department_name`, deptJoinSQL, f.employeeScope(a), from, to, lateMinutesSQL)
	rows, err := s.queryMaps(ctx, q, a.list...)
	if err != nil {
		return nil, fmt.Errorf("attendance summary: %w", err)
	}
	return &Report{Report: "attendance-summary", Period: f.meta(),
		Columns: []string{"department_name", "headcount", "present_days", "absent_days", "late_days", "attendance_rate", "overtime_hours", "piece_amount"},
		Rows:    rows, Totals: sumCols(rows, "headcount", "present_days", "absent_days", "late_days", "overtime_hours", "piece_amount")}, nil
}
