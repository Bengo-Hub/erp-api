package reports

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/accessevent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
)

func TestNewAttendanceFilter(t *testing.T) {
	to := time.Date(2026, 11, 23, 15, 0, 0, 0, time.UTC)
	f, err := NewAttendanceFilter(nil, &to, nil, nil, nil)
	if err != nil || f.From.Day() != 1 || f.To.Hour() != 0 {
		t.Fatalf("defaults: %+v err %v", f, err)
	}
	from := to.AddDate(-2, 0, 0)
	if _, err := NewAttendanceFilter(&from, &to, nil, nil, nil); err == nil {
		t.Fatal("a two-year range must be refused")
	}
	if _, err := NewAttendanceFilter(&to, &from, nil, nil, nil); err == nil {
		t.Fatal("to before from must be refused")
	}
}

func TestAfterHours(t *testing.T) {
	at := func(h, m int) time.Time { return time.Date(2026, 11, 23, h, m, 0, 0, time.UTC) }
	if afterHours(at(9, 0), "08:00", "17:00") || !afterHours(at(21, 0), "08:00", "17:00") || !afterHours(at(6, 59), "08:00", "17:00") {
		t.Fatal("day window")
	}
	if afterHours(at(23, 0), "22:00", "06:00") || !afterHours(at(12, 0), "22:00", "06:00") {
		t.Fatal("night window")
	}
	if afterHours(at(3, 0), "", "") {
		t.Fatal("no window is never after hours")
	}
}

// Every attendance report runs its SQL against a real schema and returns the expected rows.
func TestIntegration_AttendanceReports(t *testing.T) {
	client := analyticsClient(t)
	ctx := context.Background()
	svc := NewService(client)
	tenant := uuid.New()
	dept := client.Department.Create().SetTenantID(tenant).SetTitle("Packing").SaveX(ctx)
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Jane").SetLastName("Wanjiru").SetNationalID("1").
		SetEmployeeNumber("SS/2026/001").SaveX(ctx)
	client.HRDetails.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetDepartmentID(dept.ID).SaveX(ctx)
	other := client.Employee.Create().SetTenantID(tenant).SetFirstName("Otieno").SetNationalID("2").SaveX(ctx)

	day := time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)
	in := time.Date(2026, 11, 23, 5, 20, 0, 0, time.UTC)
	out := time.Date(2026, 11, 23, 14, 0, 0, 0, time.UTC)
	client.AttendanceRecord.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetDate(day).SetCheckIn(in).SetCheckOut(out).
		SetStatus(attendancerecord.StatusLate).SetTotalSecondsWorked(31200).SetRegularHours(decimal.NewFromInt(8)).
		SetOvertimeHours(decimal.RequireFromString("0.67")).
		SetMetadata(map[string]any{"late_minutes": 20, "early_leave_minutes": 60, "shift_end": "18:00"}).SaveX(ctx)
	client.AttendanceRecord.Create().SetTenantID(tenant).SetEmployeeID(other.ID).SetDate(day).
		SetStatus(attendancerecord.StatusAbsent).SaveX(ctx)
	client.LeaveRequest.Create().SetTenantID(tenant).SetEmployeeID(other.ID).SetCategoryID(uuid.New()).
		SetStartDate(day.AddDate(0, 0, 1)).SetEndDate(day.AddDate(0, 0, 2)).SetDaysRequested(decimal.NewFromInt(2)).
		SetStatus(leaverequest.StatusApproved).SaveX(ctx)
	dev := client.AttendanceDevice.Create().SetTenantID(tenant).SetSerialNumber("SN" + uuid.NewString()[:6]).SetName("Gate").SaveX(ctx)
	client.AccessEvent.Create().SetTenantID(tenant).SetDeviceID(dev.ID).SetDeviceSn(dev.SerialNumber).
		SetOccurredAt(in).SetResult(accessevent.ResultDenied).SetEventCode(27).SaveX(ctx)

	from, to := day.AddDate(0, 0, -1), day.AddDate(0, 0, 3)
	f, err := NewAttendanceFilter(&from, &to, nil, nil, nil)
	if err != nil {
		t.Fatal(err)
	}
	want := map[string]int{"attendance-register": 2, "absenteeism": 2, "lateness": 1, "early-leave": 1, "overtime": 1,
		"piece-output": 0, "access-log": 1, "device-health": 1, "attendance-summary": 2}
	producers := map[string]func(context.Context, uuid.UUID, AttendanceFilter) (*Report, error){
		"attendance-register": svc.AttendanceRegister, "absenteeism": svc.Absenteeism, "lateness": svc.Lateness,
		"early-leave": svc.EarlyLeave, "overtime": svc.Overtime, "piece-output": svc.PieceOutputReport,
		"access-log": svc.AccessLog, "device-health": svc.DeviceHealth, "attendance-summary": svc.AttendanceSummary,
	}
	for name, fn := range producers {
		rep, err := fn(ctx, tenant, f)
		if err != nil {
			t.Fatalf("%s: %v", name, err)
		}
		if len(rep.Rows) != want[name] {
			t.Fatalf("%s: %d rows, want %d: %v", name, len(rep.Rows), want[name], rep.Rows)
		}
		for _, row := range rep.Rows {
			for _, c := range rep.Columns {
				if _, ok := row[c]; !ok {
					t.Fatalf("%s: row lacks column %s", name, c)
				}
			}
		}
	}
	abs, _ := svc.Absenteeism(ctx, tenant, f)
	for _, r := range abs.Rows {
		if r["employee_name"] == "Otieno" && (toInt(r["days_on_leave"]) != 2 || toFloat(r["absence_rate"]) != 33.33) {
			t.Fatalf("absenteeism row %v", r)
		}
	}
	f.DepartmentID = &dept.ID
	if rep, _ := svc.AttendanceRegister(ctx, tenant, f); len(rep.Rows) != 1 || rep.Rows[0]["department_name"] != "Packing" {
		t.Fatalf("department filter: %v", rep.Rows)
	}

	an, err := svc.AttendanceAnalytics(ctx, tenant, day, nil, nil)
	if err != nil || an.Today.Present != 1 || an.Today.Late != 1 || an.Devices.Total != 1 || len(an.Trend30d) != 1 {
		t.Fatalf("analytics %+v err %v", an, err)
	}
}
