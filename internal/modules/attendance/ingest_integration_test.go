package attendance

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/attendancepunch"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/devicecommand"
)

// A device batch lands once (redelivery is a no-op), pairs into a record with lateness in the
// business zone, and an unknown PIN waits until HR assigns it. Unknown serials are refused and
// a queued command makes the full trip.
func TestIntegration_ADMSIngest(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	svc := NewService(client)
	tenant := uuid.New()

	shift := client.WorkShift.Create().SetTenantID(tenant).SetName("Office").
		SetStartTime("08:00").SetEndTime("17:00").SetGraceMinutes(10).SetIsDefault(true).SaveX(ctx)
	jane := client.Employee.Create().SetTenantID(tenant).SetFirstName("Jane").SetLastName("Wanjiru").
		SetNationalID("1").SetWorkShiftID(shift.ID).SaveX(ctx)
	otieno := client.Employee.Create().SetTenantID(tenant).SetFirstName("Otieno").SetNationalID("2").SaveX(ctx)
	if _, err := svc.SetDevicePIN(ctx, tenant, jane.ID, "1"); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.SetDevicePIN(ctx, tenant, otieno.ID, "1"); !errors.Is(err, ErrPINTaken) {
		t.Fatalf("duplicate PIN: %v, want ErrPINTaken", err)
	}
	serial := "CKJF" + uuid.NewString()[:8]
	if _, err := svc.CreateDevice(ctx, tenant, DeviceInput{Serial: &serial}); err != nil {
		t.Fatal(err)
	}

	if _, err := svc.DeviceBySerial(ctx, "NOPE123"); !errors.Is(err, ErrUnknownDevice) {
		t.Fatalf("unknown serial: %v", err)
	}
	dev, err := svc.DeviceBySerial(ctx, serial)
	if err != nil {
		t.Fatal(err)
	}
	if hs := svc.DeviceHandshake(ctx, dev); !strings.HasPrefix(hs, "GET OPTION FROM: "+serial) {
		t.Fatalf("handshake: %q", hs)
	}

	// Monday 23 November 2026, Nairobi wall-clock times on the device.
	batch := "1\t2026-11-23 08:16:40\t0\t15\t0\t0\n1\t2026-11-23 17:30:00\t1\t15\t0\t0\n77\t2026-11-23 08:00:00\t0\t1\t0\t0\n"
	res, err := svc.DeviceUpload(ctx, dev, "ATTLOG", "100", batch)
	if err != nil || res.Inserted != 3 || res.Unmatched != 1 {
		t.Fatalf("first upload %+v err %v", res, err)
	}
	res, err = svc.DeviceUpload(ctx, dev, "ATTLOG", "100", batch)
	if err != nil || res.Inserted != 0 || res.Duplicates != 3 {
		t.Fatalf("redelivery %+v err %v", res, err)
	}
	if _, err := svc.ProcessPendingPunches(ctx, tenant); err != nil {
		t.Fatal(err)
	}
	rec := client.AttendanceRecord.Query().Where(attendancerecord.TenantID(tenant), attendancerecord.EmployeeID(jane.ID)).OnlyX(ctx)
	if rec.Status != attendancerecord.StatusLate || rec.Metadata["late_minutes"].(float64) != 16 {
		t.Fatalf("record status %s metadata %v", rec.Status, rec.Metadata)
	}
	if !dateOnly(rec.Date).Equal(time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)) || rec.CheckOut == nil {
		t.Fatalf("record date %v check-out %v", rec.Date, rec.CheckOut)
	}
	if n := client.AttendancePunch.Query().Where(attendancepunch.TenantID(tenant), attendancepunch.EmployeeIDIsNil()).CountX(ctx); n != 1 {
		t.Fatalf("unmatched punches %d, want 1", n)
	}
	// Assigning PIN 77 attaches the waiting punch.
	if _, err := svc.SetDevicePIN(ctx, tenant, otieno.ID, "77"); err != nil {
		t.Fatal(err)
	}
	if n := client.AttendancePunch.Query().Where(attendancepunch.TenantID(tenant), attendancepunch.EmployeeIDIsNil()).CountX(ctx); n != 0 {
		t.Fatalf("unmatched punches after PIN %d, want 0", n)
	}

	cmds, err := svc.EnqueueCommand(ctx, tenant, dev.ID, CommandInput{Type: "sync_users"})
	if err != nil || len(cmds) != 2 {
		t.Fatalf("sync_users queued %d err %v", len(cmds), err)
	}
	body, err := svc.DevicePoll(ctx, dev)
	if err != nil || !strings.Contains(body, "C:1:DATA UPDATE USERINFO PIN=1\tName=Jane Wanjiru") {
		t.Fatalf("poll body %q err %v", body, err)
	}
	if again, _ := svc.DevicePoll(ctx, dev); again != "OK" {
		t.Fatalf("second poll %q, want OK", again)
	}
	if n, err := svc.DeviceCommandReply(ctx, dev, "ID=1&Return=0&CMD=DATA\nID=2&Return=-1&CMD=DATA\n"); err != nil || n != 2 {
		t.Fatalf("reply closed %d err %v", n, err)
	}
	if n := client.DeviceCommand.Query().Where(devicecommand.DeviceID(dev.ID), devicecommand.StatusEQ(devicecommand.StatusDone)).CountX(ctx); n != 1 {
		t.Fatalf("done commands %d, want 1", n)
	}

	// Auto-absent: Otieno has no record on the 24th, Jane has one; neither is on leave.
	day := time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC)
	client.AttendanceRecord.Create().SetTenantID(tenant).SetEmployeeID(jane.ID).SetDate(day).SetStatus(attendancerecord.StatusPresent).SaveX(ctx)
	n, err := svc.MarkAbsent(ctx, tenant, day, DefaultSettings())
	if err != nil || n != 1 {
		t.Fatalf("auto-absent rows %d err %v, want 1", n, err)
	}
	if n, _ := svc.MarkAbsent(ctx, tenant, day, DefaultSettings()); n != 0 {
		t.Fatalf("second auto-absent run wrote %d rows", n)
	}
}
