package attendance

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/attendanceregularisation"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/overtimerequest"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
)

func TestClockTimesNightShift(t *testing.T) {
	loc := nairobi(t)
	day := time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)
	in, out, err := clockTimes(day, "22:00", "06:00", loc)
	if err != nil || out.Sub(*in) != 8*time.Hour {
		t.Fatalf("in %v out %v err %v", in, out, err)
	}
	if _, _, err := clockTimes(day, "8am", "", loc); err == nil {
		t.Fatal("bad time accepted")
	}
	in, out, _ = clockTimes(day, "", "17:00", loc)
	if in != nil || out == nil {
		t.Fatalf("check-out only: in %v out %v", in, out)
	}
}

func TestAppendCorrectionKeepsHistory(t *testing.T) {
	meta := map[string]any{"corrections": []any{map[string]any{"reason": "first"}}}
	appendCorrection(meta, map[string]any{"reason": "second"})
	if list := meta["corrections"].([]any); len(list) != 2 {
		t.Fatalf("corrections %v", list)
	}
	p := beforePair(timesMap(nil, ptr(time.Date(2026, 11, 23, 14, 0, 0, 0, time.UTC)), "late"))
	if p.CheckIn != nil || p.CheckOut == nil || p.CheckOut.Hour() != 14 {
		t.Fatalf("before pair %+v", p)
	}
}

func ptr(t time.Time) *time.Time { return &t }

// A regularisation approved through the generic approvals decision changes the record and keeps
// before and after; an overtime request is decided the same way.
func TestIntegration_RegularisationAndOvertimeApproval(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	apr := approvals.NewService(client, nil)
	svc := NewService(client)
	svc.SetApprovals(apr)

	client.WorkShift.Create().SetTenantID(tenant).SetName("Office").SetStartTime("08:00").SetEndTime("17:00").
		SetGraceMinutes(10).SetIsDefault(true).SaveX(ctx)
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Jane").SetLastName("Wanjiru").SetNationalID("9").SaveX(ctx)
	day := time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)
	loc := nairobi(t)
	late := time.Date(2026, 11, 23, 9, 0, 0, 0, loc)
	client.AttendanceRecord.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetDate(day).
		SetCheckIn(late).SetStatus(attendancerecord.StatusLate).SaveX(ctx)

	reg, err := svc.CreateRegularisation(ctx, tenant, RegularisationInput{
		EmployeeID: emp.ID, Date: day, CheckIn: "07:55", CheckOut: "17:05", Reason: "Device was offline"})
	if err != nil || reg.ApprovalRequestID == nil || reg.Before.CheckIn == nil {
		t.Fatalf("create: %+v err %v", reg, err)
	}
	dec, err := apr.DecideAndApply(ctx, tenant, approvals.DecisionInput{RequestID: *reg.ApprovalRequestID, Approve: true})
	if err != nil || !dec.Finished || dec.ApplyErr != nil {
		t.Fatalf("decide: %+v err %v", dec, err)
	}
	rec := client.AttendanceRecord.Query().Where(attendancerecord.TenantID(tenant), attendancerecord.EmployeeID(emp.ID)).OnlyX(ctx)
	if rec.Status != attendancerecord.StatusPresent || rec.CheckOut == nil {
		t.Fatalf("record after correction: %s %v", rec.Status, rec.CheckOut)
	}
	if list, ok := rec.Metadata["corrections"].([]any); !ok || len(list) != 1 {
		t.Fatalf("corrections %v", rec.Metadata["corrections"])
	}
	if st := client.AttendanceRegularisation.GetX(ctx, reg.ID).Status; st != attendanceregularisation.StatusApproved {
		t.Fatalf("regularisation status %s", st)
	}

	// ESS overtime is refused while the tenant has not allowed it; HR may still file.
	if _, err := svc.CreateOvertimeRequest(ctx, tenant, OvertimeInput{EmployeeID: emp.ID, Date: day, Hours: decimal.NewFromInt(2), Self: true}); err != ErrOvertimeApplicationsOff {
		t.Fatalf("self overtime: %v", err)
	}
	ot, err := svc.CreateOvertimeRequest(ctx, tenant, OvertimeInput{EmployeeID: emp.ID, Date: day, Hours: decimal.NewFromInt(2)})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := apr.DecideAndApply(ctx, tenant, approvals.DecisionInput{RequestID: *ot.ApprovalRequestID, Approve: true}); err != nil {
		t.Fatal(err)
	}
	if st := client.OvertimeRequest.GetX(ctx, ot.ID).Status; st != overtimerequest.StatusApproved {
		t.Fatalf("overtime status %s", st)
	}
	got, err := svc.ApprovedOvertime(ctx, tenant, day, day)
	if err != nil || !got[emp.ID][day].Equal(decimal.NewFromInt(2)) {
		t.Fatalf("approved overtime %v err %v", got, err)
	}
}
