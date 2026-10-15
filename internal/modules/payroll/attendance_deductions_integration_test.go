package payroll

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancededuction"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerule"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

func TestIntegration_AttendanceDeductions(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	d := decimal.RequireFromString
	sep := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)
	day := func(n int) time.Time { return sep.AddDate(0, 0, n-1) }
	// Check-ins are local business time; no company settings or outlet zone means Africa/Nairobi.
	// The database hands them back in its own session zone, which must not shift the lateness.
	nairobi, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		t.Fatal(err)
	}
	at := func(n, h, m int) *time.Time {
		v := time.Date(2026, 9, n, h, m, 0, 0, nairobi)
		return &v
	}

	a := client.Employee.Create().SetTenantID(tenant).SetFirstName("Amina").SetLastName("W").SaveX(ctx)
	b := client.Employee.Create().SetTenantID(tenant).SetFirstName("Baraka").SaveX(ctx) // no salary
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetMonthlySalary(d("22000")).SaveX(ctx)
	start := "08:00"
	shift := client.WorkShift.Create().SetTenantID(tenant).SetName("Day").SetStartTime(start).SetGraceMinutes(5).SaveX(ctx)
	client.AttendanceRule.Create().SetTenantID(tenant).SetName("Late").SetRuleType(attendancerule.RuleTypeLatePolicy).
		SetLatePenaltyType("fixed").SetLatePenaltyValue(d("200")).SetLateThresholdMinutes(15).SaveX(ctx)

	late := func(emp uuid.UUID, n, h, m int) {
		client.AttendanceRecord.Create().SetTenantID(tenant).SetEmployeeID(emp).SetDate(day(n)).
			SetWorkShiftID(shift.ID).SetCheckIn(*at(n, h, m)).SetStatus(attendancerecord.StatusLate).SaveX(ctx)
	}
	absent := func(emp uuid.UUID, n int) {
		client.AttendanceRecord.Create().SetTenantID(tenant).SetEmployeeID(emp).SetDate(day(n)).
			SetStatus(attendancerecord.StatusAbsent).SaveX(ctx)
	}
	late(a.ID, 1, 8, 10) // 10 minutes: inside the 15-minute threshold
	late(a.ID, 2, 8, 30)
	late(a.ID, 3, 9, 0)
	absent(a.ID, 7)
	absent(a.ID, 8)
	absent(a.ID, 9) // covered by approved leave below
	late(b.ID, 2, 9, 0)
	absent(b.ID, 7)
	cat := client.LeaveCategory.Create().SetTenantID(tenant).SetName("Annual").SaveX(ctx)
	client.LeaveRequest.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetCategoryID(cat.ID).
		SetStartDate(day(9)).SetEndDate(day(9)).SetStatus(leaverequest.StatusApproved).SaveX(ctx)
	// October is a different month and is never touched.
	client.AttendanceRecord.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetDate(sep.AddDate(0, 1, 0)).
		SetStatus(attendancerecord.StatusAbsent).SaveX(ctx)

	svc := NewService(client, nil)
	sum, err := svc.ComputeAttendanceDeductions(ctx, tenant, sep)
	if err != nil {
		t.Fatal(err)
	}
	if sum.Created != 2 || sum.Updated != 0 || sum.Removed != 0 {
		t.Fatalf("first compute = %+v, want 2 rows for Amina only (Baraka has no salary)", sum)
	}
	rows, total, amount, err := svc.ListAttendanceDeductions(ctx, tenant, AttendanceDeductionFilter{Month: sep})
	if err != nil || total != 2 || !amount.Equal(d("2400")) {
		t.Fatalf("list = %d rows, total %s, %v; want 2 rows worth 2400", total, amount, err)
	}
	byKind := map[string]AttendanceDeductionModel{}
	for _, r := range rows {
		byKind[r.Kind] = r
	}
	if r := byKind["late"]; !r.Amount.Equal(d("400")) || r.Occurrences != 2 || r.Minutes != 90 || r.EmployeeName != "Amina W" || r.Status != "pending" {
		t.Errorf("late row = %+v, want 2 arrivals, 90 minutes, 400", r)
	}
	if r := byKind["absence"]; !r.Amount.Equal(d("2000")) || r.Occurrences != 2 {
		t.Errorf("absence row = %+v, want 2 unexcused days at 1000", r)
	}

	// Review: approve the late row, waive the absence row.
	reviewer := uuid.New()
	if n, err := svc.ReviewAttendanceDeductions(ctx, tenant, reviewer, []uuid.UUID{byKind["late"].ID}, "approve", ""); err != nil || n != 1 {
		t.Fatalf("approve = %d, %v", n, err)
	}
	if n, err := svc.ReviewAttendanceDeductions(ctx, tenant, reviewer, []uuid.UUID{byKind["absence"].ID}, "waive", "Sick, note to follow"); err != nil || n != 1 {
		t.Fatalf("waive = %d, %v", n, err)
	}
	// Approving an already approved row changes nothing; another tenant cannot touch the rows.
	if n, _ := svc.ReviewAttendanceDeductions(ctx, tenant, reviewer, []uuid.UUID{byKind["late"].ID}, "approve", ""); n != 0 {
		t.Errorf("re-approve changed %d rows", n)
	}
	if n, _ := svc.ReviewAttendanceDeductions(ctx, uuid.New(), reviewer, []uuid.UUID{byKind["absence"].ID}, "reopen", ""); n != 0 {
		t.Errorf("another tenant reopened %d rows", n)
	}
	if _, err := svc.ReviewAttendanceDeductions(ctx, tenant, reviewer, []uuid.UUID{byKind["late"].ID}, "delete", ""); err == nil {
		t.Error("an unknown action must fail")
	}

	// Recompute after more absence: reviewed rows stay exactly as they were.
	absent(a.ID, 10)
	sum, err = svc.ComputeAttendanceDeductions(ctx, tenant, sep)
	if err != nil || sum.Reviewed != 2 || sum.Created != 0 {
		t.Fatalf("recompute = %+v %v, want both reviewed rows kept", sum, err)
	}
	if got := client.AttendanceDeduction.GetX(ctx, byKind["absence"].ID); got.Status != attendancededuction.StatusWaived || got.Occurrences != 2 {
		t.Errorf("waived row changed on recompute: %+v", got)
	}

	// Reopen the absence row, recompute: it is pending again and picks up the new day.
	if n, _ := svc.ReviewAttendanceDeductions(ctx, tenant, reviewer, []uuid.UUID{byKind["absence"].ID}, "reopen", ""); n != 1 {
		t.Fatal("reopen failed")
	}
	if _, err := svc.ComputeAttendanceDeductions(ctx, tenant, sep); err != nil {
		t.Fatal(err)
	}
	if got := client.AttendanceDeduction.GetX(ctx, byKind["absence"].ID); got.Status != attendancededuction.StatusPending || got.Occurrences != 3 || !got.Amount.Equal(d("3000")) || got.ReviewedBy != nil {
		t.Errorf("reopened absence after recompute = %+v, want 3 days pending", got)
	}

	// A pending row whose basis disappears is removed on recompute.
	client.AttendanceRecord.Delete().Where(attendancerecord.EmployeeID(a.ID), attendancerecord.StatusEQ(attendancerecord.StatusAbsent)).ExecX(ctx)
	if sum, err = svc.ComputeAttendanceDeductions(ctx, tenant, sep); err != nil || sum.Removed != 1 {
		t.Fatalf("recompute after attendance corrected = %+v %v, want the pending absence removed", sum, err)
	}

	// The run loads only approved (or applied) rows, then marks them applied to the payslip.
	approved, err := svc.approvedAttendanceDeductions(ctx, tenant, sep.AddDate(0, 0, 14))
	if err != nil || len(approved[a.ID]) != 1 || approved[a.ID][0].Kind != attendancededuction.KindLate {
		t.Fatalf("approved for the run = %+v %v, want the late row only", approved, err)
	}
	slip := client.Payslip.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetPaymentPeriod(sep).SetGrossPay(d("21600")).SaveX(ctx)
	if err := svc.markAttendanceApplied(ctx, tenant, slip.ID, []uuid.UUID{approved[a.ID][0].ID}); err != nil {
		t.Fatal(err)
	}
	applied := client.AttendanceDeduction.GetX(ctx, approved[a.ID][0].ID)
	if applied.Status != attendancededuction.StatusApplied || applied.PayslipID == nil || *applied.PayslipID != slip.ID {
		t.Fatalf("applied row = %+v", applied)
	}
	if n, _ := svc.ReviewAttendanceDeductions(ctx, tenant, reviewer, []uuid.UUID{applied.ID}, "reopen", ""); n != 0 {
		t.Error("an applied row must never be reopened")
	}
	if again, _ := svc.approvedAttendanceDeductions(ctx, tenant, sep); len(again[a.ID]) != 1 {
		t.Error("a re-run of the month must still deduct applied rows")
	}

	// Payslip lines: basic less the attendance deduction adds up to the payslip's gross.
	items := EmployeeItemized{
		Attendance:    []LabeledAmount{{Label: attendanceLabel(applied), Amount: applied.Amount}},
		AttendanceIDs: []uuid.UUID{applied.ID},
	}
	res := payrollengine.PayslipResult{GrossPay: d("21600"), UnpaidTime: d("400")}
	if err := svc.writePayslipLines(ctx, tenant, slip.ID, d("22000"), res, items); err != nil {
		t.Fatal(err)
	}
	earnings := decimal.Zero
	var lines []*ent.PayslipLine
	lines = client.PayslipLine.Query().Where(payslipline.PayslipID(slip.ID), payslipline.Section(secEarningCash)).AllX(ctx)
	for _, l := range lines {
		earnings = earnings.Add(l.CashAmount)
	}
	if !earnings.Equal(res.GrossPay) || len(lines) != 2 {
		t.Errorf("cash earning lines sum to %s over %d lines, want the gross 21600 (basic and the deduction)", earnings, len(lines))
	}
}
