package reports

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/timesheet"
)

func TestIntegration_WorkforceFigures(t *testing.T) {
	client := analyticsClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	d := decimal.RequireFromString
	now := time.Now().UTC()
	from, to := now.AddDate(0, -1, 0), now

	emp := func(terminated bool, at *time.Time) uuid.UUID {
		c := client.Employee.Create().SetTenantID(tenant).SetFirstName("E").SetTerminated(terminated)
		if at != nil {
			c = c.SetTerminatedAt(*at)
		}
		return c.SaveX(ctx).ID
	}
	a, b := emp(false, nil), emp(false, nil)
	inPeriod, before := now.AddDate(0, 0, -5), now.AddDate(0, -3, 0)
	emp(true, &inPeriod)
	emp(true, &before) // exited before the period
	emp(true, nil)     // exit date unknown

	client.AttendanceRecord.Create().SetTenantID(tenant).SetEmployeeID(a).SetDate(now.AddDate(0, 0, -2)).SetOvertimeHours(d("2.5")).SaveX(ctx)
	client.AttendanceRecord.Create().SetTenantID(tenant).SetEmployeeID(b).SetDate(now.AddDate(0, -2, 0)).SetOvertimeHours(d("9")).SaveX(ctx) // outside

	sheet := func(employeeID uuid.UUID, status timesheet.Status) uuid.UUID {
		return client.Timesheet.Create().SetTenantID(tenant).SetEmployeeID(employeeID).SetPeriodStart(from).SetPeriodEnd(to).SetStatus(status).SaveX(ctx).ID
	}
	client.TimesheetEntry.Create().SetTenantID(tenant).SetTimesheetID(sheet(a, timesheet.StatusApproved)).SetDate(now.AddDate(0, 0, -3)).SetOvertimeHours(d("4")).SaveX(ctx)
	client.TimesheetEntry.Create().SetTenantID(tenant).SetTimesheetID(sheet(b, timesheet.StatusDraft)).SetDate(now.AddDate(0, 0, -3)).SetOvertimeHours(d("7")).SaveX(ctx)

	cat := uuid.New()
	client.LeaveBalance.Create().SetTenantID(tenant).SetEmployeeID(a).SetCategoryID(cat).SetYear(now.Year()).SetDaysRemaining(d("10")).SaveX(ctx)
	client.LeaveBalance.Create().SetTenantID(tenant).SetEmployeeID(b).SetCategoryID(cat).SetYear(now.Year()).SetDaysRemaining(d("5")).SaveX(ctx)
	client.LeaveBalance.Create().SetTenantID(tenant).SetEmployeeID(a).SetCategoryID(cat).SetYear(now.Year() - 1).SetDaysRemaining(d("30")).SaveX(ctx) // last year
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(a).SetDailyRate(d("1000")).SetIsActive(true).SaveX(ctx)
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(a).SetDailyRate(d("400")).SetIsActive(false).SaveX(ctx) // old record
	// b has no salary record: days count, value zero.

	out := &HRMAnalytics{Headcount: 2, NewHires: 0}
	if err := NewService(client).workforceFigures(ctx, tenant, from, to, out); err != nil {
		t.Fatal(err)
	}
	if out.Exits != 1 {
		t.Errorf("exits = %d, want 1", out.Exits)
	}
	if out.TurnoverPct == nil || *out.TurnoverPct != 40 { // 1 / ((3 + 2) / 2)
		t.Errorf("turnover = %v, want 40", out.TurnoverPct)
	}
	if !out.OvertimeAttendanceHours.Equal(d("2.5")) || !out.OvertimeTimesheetHours.Equal(d("4")) {
		t.Errorf("overtime attendance/timesheet = %s/%s, want 2.5/4", out.OvertimeAttendanceHours, out.OvertimeTimesheetHours)
	}
	if !out.LeaveDaysRemaining.Equal(d("15")) || !out.LeaveLiability.Equal(d("10000")) {
		t.Errorf("leave days/liability = %s/%s, want 15/10000", out.LeaveDaysRemaining, out.LeaveLiability)
	}
}

func TestTurnoverPct(t *testing.T) {
	if turnoverPct(0, 0, 0) != nil {
		t.Error("no headcount: no turnover")
	}
	if v := turnoverPct(10, 0, 0); v == nil || *v != 0 {
		t.Errorf("no exits = %v", v)
	}
}
