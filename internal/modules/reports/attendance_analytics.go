package reports

import (
	"context"
	"fmt"
	"time"

	sharedcache "github.com/Bengo-Hub/cache"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// AttendanceAnalytics is the attendance dashboard payload (GET /reports/attendance-analytics).
type AttendanceAnalytics struct {
	Date  string `json:"date"`
	Today struct {
		Expected         int `json:"expected"`
		Present          int `json:"present"`
		Late             int `json:"late"`
		Absent           int `json:"absent"`
		OnLeave          int `json:"on_leave"`
		Field            int `json:"field"`
		EarlyLeave       int `json:"early_leave"`
		UnmatchedPunches int `json:"unmatched_punches"`
	} `json:"today"`
	Trend30d           []AttendanceTrendPoint `json:"trend_30d"`
	ByDepartment       []AttendanceDeptPoint  `json:"by_department"`
	OvertimeHoursMonth float64                `json:"overtime_hours_month"`
	PieceOutputMonth   struct {
		Quantity float64 `json:"quantity"`
		Amount   float64 `json:"amount"`
	} `json:"piece_output_month"`
	Devices struct {
		Total  int `json:"total"`
		Online int `json:"online"`
	} `json:"devices"`
}

// AttendanceTrendPoint is one day of the 30-day trend.
type AttendanceTrendPoint struct {
	Date    string `json:"date"`
	Present int    `json:"present"`
	Late    int    `json:"late"`
	Absent  int    `json:"absent"`
}

// AttendanceDeptPoint is one department's figures for the day.
type AttendanceDeptPoint struct {
	Department string `json:"department"`
	Present    int    `json:"present"`
	Late       int    `json:"late"`
	Absent     int    `json:"absent"`
}

// analyticsCache keeps a dashboard answer for a minute per tenant and filter, so a wall of
// open dashboards does not repeat the grouped queries.
var analyticsCache = sharedcache.NewLocal[string, *AttendanceAnalytics](1000, time.Minute)

func toInt(v any) int {
	switch n := v.(type) {
	case int64:
		return int(n)
	case int32:
		return int(n)
	case float64:
		return int(n)
	}
	return 0
}

func toFloat(v any) float64 {
	switch n := v.(type) {
	case float64:
		return n
	case int64:
		return float64(n)
	}
	return 0
}

// AttendanceAnalytics answers the dashboard for one day (default today in the company zone),
// optionally for one outlet or department. Every figure is one grouped query.
func (s *Service) AttendanceAnalytics(ctx context.Context, tenantID uuid.UUID, day time.Time, outlet, dept *uuid.UUID) (*AttendanceAnalytics, error) {
	att := attendance.NewService(s.orm)
	loc := att.TenantZone(ctx, tenantID)
	if day.IsZero() {
		y, m, d := time.Now().In(loc).Date()
		day = time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
	}
	key := fmt.Sprintf("%s|%s|%v|%v", tenantID, day.Format("2006-01-02"), outlet, dept)
	return analyticsCache.GetOrLoad(key, func() (*AttendanceAnalytics, error) {
		return s.attendanceAnalytics(ctx, att, loc, tenantID, day, outlet, dept)
	})
}

func (s *Service) attendanceAnalytics(ctx context.Context, att *attendance.Service, loc *time.Location, tenantID uuid.UUID, day time.Time, outlet, dept *uuid.UUID) (*AttendanceAnalytics, error) {
	out := &AttendanceAnalytics{Date: day.Format("2006-01-02"), Trend30d: []AttendanceTrendPoint{}, ByDepartment: []AttendanceDeptPoint{}}
	f := AttendanceFilter{From: day, To: day, OutletID: outlet, DepartmentID: dept}

	// Scoped employees, who is expected today, who is on leave today.
	a := &sqlArgs{list: []any{tenantID}}
	empRows, err := s.queryMaps(ctx, `SELECT e.id::text AS id FROM employees e WHERE `+f.employeeScope(a)+` AND e.terminated = false`, a.list...)
	if err != nil {
		return nil, fmt.Errorf("analytics employees: %w", err)
	}
	ids := make([]uuid.UUID, 0, len(empRows))
	for _, r := range empRows {
		if id, err := uuid.Parse(fmt.Sprint(r["id"])); err == nil {
			ids = append(ids, id)
		}
	}
	if len(ids) == 0 {
		return out, nil
	}
	expected, err := att.ExpectedToWork(ctx, tenantID, day, ids)
	if err != nil {
		return nil, fmt.Errorf("analytics expected: %w", err)
	}
	out.Today.Expected = len(expected)

	next := day.AddDate(0, 0, 1)
	leaveRows, err := s.queryMaps(ctx, `SELECT DISTINCT l.employee_id::text AS id FROM leave_requests l
WHERE l.tenant_id = $1 AND l.status = 'approved' AND l.start_date < $2 AND l.end_date >= $3 AND l.employee_id = ANY($4)`,
		tenantID, next, day, ids)
	if err != nil {
		return nil, fmt.Errorf("analytics leave: %w", err)
	}
	onLeave := map[string]bool{}
	for _, r := range leaveRows {
		onLeave[fmt.Sprint(r["id"])] = true
	}
	out.Today.OnLeave = len(onLeave)

	recRows, err := s.queryMaps(ctx, `SELECT r.employee_id::text AS id, r.status,
  `+lateMinutesSQL+` AS late_min, `+earlyMinutesSQL+` AS early_min,
  COALESCE(r.metadata->>'attendance_mode', '') AS mode, COALESCE(dep.title, 'No department') AS dept
FROM attendance_records r JOIN employees e ON e.id = r.employee_id `+deptJoinSQL+`
WHERE r.tenant_id = $1 AND r.date >= $2 AND r.date < $3 AND e.id = ANY($4)`, tenantID, day, next, ids)
	if err != nil {
		return nil, fmt.Errorf("analytics today: %w", err)
	}
	present := map[string]bool{}
	byDept := map[string]*AttendanceDeptPoint{}
	deptOf := func(name string) *AttendanceDeptPoint {
		if byDept[name] == nil {
			byDept[name] = &AttendanceDeptPoint{Department: name}
		}
		return byDept[name]
	}
	for _, r := range recRows {
		d := deptOf(fmt.Sprint(r["dept"]))
		if r["status"] == "absent" {
			d.Absent++
			continue
		}
		present[fmt.Sprint(r["id"])] = true
		out.Today.Present++
		d.Present++
		if r["status"] == "late" || toInt(r["late_min"]) > 0 {
			out.Today.Late++
			d.Late++
		}
		if toInt(r["early_min"]) > 0 {
			out.Today.EarlyLeave++
		}
		if r["mode"] == attendance.AttendanceModeField {
			out.Today.Field++
		}
	}
	// Absent: expected today, not present and not on leave (whether or not auto-absent ran yet).
	for _, id := range expected {
		if !present[id.String()] && !onLeave[id.String()] {
			out.Today.Absent++
		}
	}
	for _, d := range byDept {
		out.ByDepartment = append(out.ByDepartment, *d)
	}

	dayStart := time.Date(day.Year(), day.Month(), day.Day(), 0, 0, 0, 0, loc)
	if rows, err := s.queryMaps(ctx, `SELECT count(*)::bigint AS n FROM attendance_punches
WHERE tenant_id = $1 AND employee_id IS NULL AND punched_at >= $2 AND punched_at < $3`, tenantID, dayStart, dayStart.AddDate(0, 0, 1)); err == nil && len(rows) == 1 {
		out.Today.UnmatchedPunches = toInt(rows[0]["n"])
	}

	trend, err := s.queryMaps(ctx, `SELECT to_char(r.date AT TIME ZONE 'UTC', 'YYYY-MM-DD') AS day,
  count(*) FILTER (WHERE r.status <> 'absent')::bigint AS present,
  count(*) FILTER (WHERE r.status = 'late' OR `+lateMinutesSQL+` > 0)::bigint AS late,
  count(*) FILTER (WHERE r.status = 'absent')::bigint AS absent
FROM attendance_records r
WHERE r.tenant_id = $1 AND r.date >= $2 AND r.date < $3 AND r.employee_id = ANY($4)
GROUP BY day ORDER BY day`, tenantID, day.AddDate(0, 0, -29), next, ids)
	if err != nil {
		return nil, fmt.Errorf("analytics trend: %w", err)
	}
	for _, r := range trend {
		out.Trend30d = append(out.Trend30d, AttendanceTrendPoint{Date: fmt.Sprint(r["day"]),
			Present: toInt(r["present"]), Late: toInt(r["late"]), Absent: toInt(r["absent"])})
	}

	monthStart := time.Date(day.Year(), day.Month(), 1, 0, 0, 0, 0, time.UTC)
	if rows, err := s.queryMaps(ctx, `SELECT COALESCE(sum(overtime_hours), 0)::float8 AS h FROM attendance_records
WHERE tenant_id = $1 AND date >= $2 AND date < $3 AND employee_id = ANY($4)`, tenantID, monthStart, next, ids); err == nil && len(rows) == 1 {
		out.OvertimeHoursMonth = toFloat(rows[0]["h"])
	}
	if rows, err := s.queryMaps(ctx, `SELECT COALESCE(sum(quantity - rejected_quantity), 0)::float8 AS q, COALESCE(sum(amount), 0)::float8 AS a
FROM piece_outputs WHERE tenant_id = $1 AND date >= $2 AND date < $3 AND status IN ('approved', 'paid') AND employee_id = ANY($4)`,
		tenantID, monthStart, next, ids); err == nil && len(rows) == 1 {
		out.PieceOutputMonth.Quantity, out.PieceOutputMonth.Amount = toFloat(rows[0]["q"]), toFloat(rows[0]["a"])
	}

	st, err := att.GetSettings(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	devArgs := []any{tenantID, time.Now().Add(-time.Duration(st.DeviceOnlineMinutes) * time.Minute)}
	devQ := `SELECT count(*)::bigint AS total, count(*) FILTER (WHERE last_seen_at >= $2)::bigint AS online
FROM attendance_devices WHERE tenant_id = $1 AND active = true`
	if outlet != nil {
		devQ += ` AND outlet_id = $3`
		devArgs = append(devArgs, *outlet)
	}
	if rows, err := s.queryMaps(ctx, devQ, devArgs...); err == nil && len(rows) == 1 {
		out.Devices.Total, out.Devices.Online = toInt(rows[0]["total"]), toInt(rows[0]["online"])
	}
	return out, nil
}
