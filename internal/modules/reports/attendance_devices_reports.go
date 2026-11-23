package reports

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/accessevent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancedevice"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// afterHours reports whether a local clock time falls outside the business day [start, end]
// ("HH:MM"; a window that ends before it starts runs past midnight). No window means never.
func afterHours(local time.Time, start, end string) bool {
	if start == "" || end == "" {
		return false
	}
	hm := local.Format("15:04")
	if start <= end {
		return hm < start || hm > end
	}
	return hm < start && hm > end
}

// AccessLog lists door events with names, after-hours flag and a reason. After hours means
// outside the tenant default shift's start and end in the company zone.
func (s *Service) AccessLog(ctx context.Context, tenantID uuid.UUID, f AttendanceFilter) (*Report, error) {
	att := attendance.NewService(s.orm)
	loc := att.TenantZone(ctx, tenantID)
	from := time.Date(f.From.Year(), f.From.Month(), f.From.Day(), 0, 0, 0, 0, loc)
	to := time.Date(f.To.Year(), f.To.Month(), f.To.Day(), 0, 0, 0, 0, loc).AddDate(0, 0, 1)
	q := s.orm.AccessEvent.Query().Where(accessevent.TenantID(tenantID),
		accessevent.OccurredAtGTE(from), accessevent.OccurredAtLT(to))
	if f.EmployeeID != nil {
		q = q.Where(accessevent.EmployeeID(*f.EmployeeID))
	}
	if f.OutletID != nil {
		devs, err := s.orm.AttendanceDevice.Query().Where(attendancedevice.TenantID(tenantID),
			attendancedevice.OutletID(*f.OutletID)).IDs(ctx)
		if err != nil {
			return nil, err
		}
		q = q.Where(accessevent.DeviceIDIn(devs...))
	}
	events, err := q.Order(ent.Asc(accessevent.FieldOccurredAt)).Limit(maxReportRows).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("access log: %w", err)
	}
	var start, end string
	if def, err := s.orm.WorkShift.Query().Where(workshift.TenantID(tenantID), workshift.IsDefault(true)).First(ctx); err == nil &&
		def.StartTime != nil && def.EndTime != nil {
		start, end = *def.StartTime, *def.EndTime
	}
	empIDs, devIDs := []uuid.UUID{}, []uuid.UUID{}
	for _, e := range events {
		devIDs = append(devIDs, e.DeviceID)
		if e.EmployeeID != nil {
			empIDs = append(empIDs, *e.EmployeeID)
		}
	}
	names, err := s.employeeNames(ctx, tenantID, empIDs, f.DepartmentID)
	if err != nil {
		return nil, err
	}
	devNames := map[uuid.UUID]string{}
	if len(devIDs) > 0 {
		devs, err := s.orm.AttendanceDevice.Query().Where(attendancedevice.TenantID(tenantID), attendancedevice.IDIn(devIDs...)).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, d := range devs {
			devNames[d.ID] = d.Name
		}
	}
	rows := make([]map[string]any, 0, len(events))
	denied := 0
	for _, e := range events {
		name := ""
		if e.EmployeeID != nil {
			n, ok := names[*e.EmployeeID]
			if !ok && f.DepartmentID != nil {
				continue // outside the department asked for
			}
			name = n
		} else if f.DepartmentID != nil {
			continue
		}
		if e.Result == accessevent.ResultDenied {
			denied++
		}
		rows = append(rows, map[string]any{
			"occurred_at": e.OccurredAt.UTC().Format(time.RFC3339), "employee_name": name, "door": e.Door,
			"device_name": devNames[e.DeviceID], "result": string(e.Result),
			"after_hours": afterHours(e.OccurredAt.In(loc), start, end), "verify_mode": e.VerifyMode,
			"reason": attendance.AccessReason(e),
		})
	}
	return &Report{Report: "access-log", Period: f.meta(),
		Columns: []string{"occurred_at", "employee_name", "door", "device_name", "result", "after_hours", "verify_mode", "reason"},
		Rows:    rows, Totals: map[string]any{"events": len(rows), "denied": denied}}, nil
}

// employeeNames maps employee ids to names, keeping only those in dept when it is set.
func (s *Service) employeeNames(ctx context.Context, tenantID uuid.UUID, ids []uuid.UUID, dept *uuid.UUID) (map[uuid.UUID]string, error) {
	out := map[uuid.UUID]string{}
	if len(ids) == 0 {
		return out, nil
	}
	a := &sqlArgs{list: []any{tenantID}}
	where := (AttendanceFilter{DepartmentID: dept}).employeeScope(a)
	q := fmt.Sprintf(`SELECT e.id::text AS id, %s AS name FROM employees e WHERE %s AND e.id = ANY(%s)`, empNameSQL, where, a.add(ids))
	rows, err := s.queryMaps(ctx, q, a.list...)
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		if id, err := uuid.Parse(fmt.Sprint(r["id"])); err == nil {
			out[id] = strings.TrimSpace(fmt.Sprint(r["name"]))
		}
	}
	return out, nil
}

// DeviceHealth lists each device with its status and the range's punches, unmatched punches
// and failed commands. Department and employee filters do not apply to devices.
func (s *Service) DeviceHealth(ctx context.Context, tenantID uuid.UUID, f AttendanceFilter) (*Report, error) {
	att := attendance.NewService(s.orm)
	st, err := att.GetSettings(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	a := &sqlArgs{list: []any{tenantID}}
	from, to := a.add(f.From), a.add(f.To.AddDate(0, 0, 1))
	outletCond := ""
	if f.OutletID != nil {
		outletCond = " AND d.outlet_id = " + a.add(*f.OutletID)
	}
	q := fmt.Sprintf(`
SELECT d.id::text AS id, d.name AS device_name, d.serial_number AS serial, COALESCE(o.name, '') AS outlet_name,
       d.mode, d.last_seen_at, COALESCE(d.firmware, '') AS firmware,
       (SELECT count(*) FROM attendance_punches p WHERE p.device_id = d.id AND p.punched_at >= %[1]s AND p.punched_at < %[2]s)::bigint AS punch_count,
       (SELECT count(*) FROM attendance_punches p WHERE p.device_id = d.id AND p.employee_id IS NULL AND p.punched_at >= %[1]s AND p.punched_at < %[2]s)::bigint AS unmatched_punches,
       (SELECT count(*) FROM device_commands c WHERE c.device_id = d.id AND c.status = 'failed' AND c.created_at >= %[1]s AND c.created_at < %[2]s)::bigint AS commands_failed
FROM attendance_devices d
LEFT JOIN auth_outlets o ON o.id = d.outlet_id
WHERE d.tenant_id = $1%[3]s
ORDER BY d.name`, from, to, outletCond)
	rows, err := s.queryMaps(ctx, q, a.list...)
	if err != nil {
		return nil, fmt.Errorf("device health: %w", err)
	}
	window := time.Duration(st.DeviceOnlineMinutes) * time.Minute
	online := 0
	for _, r := range rows {
		delete(r, "id")
		seen, _ := r["last_seen_at"].(time.Time)
		r["online"] = !seen.IsZero() && time.Since(seen) <= window
		if !seen.IsZero() {
			r["last_seen_at"] = seen.UTC().Format(time.RFC3339)
			if r["online"] == true {
				online++
			}
		}
	}
	tot := sumCols(rows, "punch_count", "unmatched_punches", "commands_failed")
	tot["devices"], tot["online"] = len(rows), online
	return &Report{Report: "device-health", Period: f.meta(),
		Columns: []string{"device_name", "serial", "outlet_name", "mode", "online", "last_seen_at", "punch_count", "unmatched_punches", "commands_failed", "firmware"},
		Rows:    rows, Totals: tot}, nil
}
