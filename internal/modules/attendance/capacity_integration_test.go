package attendance

import (
	"context"
	"strings"
	"testing"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
)

// One read answers every user in order: a configured employee gets the shift's weeks with
// approved leave (never pending) and the tenant's national holidays taken off; an employee without
// a shift, a terminated one, a user without an employee and an unknown id come back unconfigured;
// another tenant's data never counts.
func TestIntegration_Capacity(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	tenant, other := uuid.New(), uuid.New()

	shift := client.WorkShift.Create().SetTenantID(tenant).SetName("Office").SetTotalHoursPerWeek(dec("40")).SaveX(ctx)
	user := func(tid uuid.UUID) (string, uuid.UUID) {
		ext := uuid.NewString()
		cu := client.CustomUser.Create().SetTenantID(tid).SetExternalID(ext).SetEmail(ext[:8] + "@example.com").SaveX(ctx)
		return ext, cu.ID
	}
	employee := func(tid, cu uuid.UUID, shiftID *uuid.UUID, terminated bool) *ent.Employee {
		b := client.Employee.Create().SetTenantID(tid).SetUserID(cu).SetTerminated(terminated)
		if shiftID != nil {
			b = b.SetWorkShiftID(*shiftID)
		}
		return b.SaveX(ctx)
	}
	worker, workerCU := user(tenant)
	ana := employee(tenant, workerCU, &shift.ID, false)
	noShift, noShiftCU := user(tenant)
	employee(tenant, noShiftCU, nil, false)
	gone, goneCU := user(tenant)
	employee(tenant, goneCU, &shift.ID, true)
	noEmployee, _ := user(tenant)
	elsewhere, elsewhereCU := user(other)
	employee(other, elsewhereCU, &shift.ID, false) // another tenant's employee: not this tenant's capacity

	leave := func(tid, emp uuid.UUID, from, to, days string, status leaverequest.Status) {
		client.LeaveRequest.Create().SetTenantID(tid).SetEmployeeID(emp).SetCategoryID(uuid.New()).
			SetStartDate(day(from)).SetEndDate(day(to)).SetDaysRequested(dec(days)).SetStatus(status).ExecX(ctx)
	}
	leave(tenant, ana.ID, "2026-11-19", "2026-11-20", "2", leaverequest.StatusApproved) // Thu-Fri
	leave(tenant, ana.ID, "2026-11-23", "2026-11-23", "1", leaverequest.StatusPending)  // not approved
	client.PublicHoliday.Create().SetTenantID(tenant).SetName("Holiday").SetDate(day("2026-11-17")).ExecX(ctx)
	client.PublicHoliday.Create().SetTenantID(other).SetName("Elsewhere").SetDate(day("2026-11-24")).ExecX(ctx)

	unknown := uuid.NewString()
	ids := []string{strings.ToUpper(worker), noShift, gone, noEmployee, elsewhere, unknown}
	got, err := NewService(client).Capacity(ctx, tenant, ids, day("2026-11-18"), day("2026-11-24"))
	if err != nil {
		t.Fatal(err)
	}
	if len(got) != len(ids) {
		t.Fatalf("got %d rows for %d ids", len(got), len(ids))
	}
	w := got[0]
	if w.AuthUserID != worker || !w.HasEmployee || !w.Configured || w.WorkShift != "Office" || !w.WeeklyHours.Equal(dec("40")) || len(w.Weeks) != 2 {
		t.Fatalf("configured worker = %+v", w)
	}
	if w.Weeks[0].WeekStart != "2026-11-16" || !w.Weeks[0].Hours.Equal(dec("16")) ||
		!w.Weeks[0].LeaveHours.Equal(dec("16")) || !w.Weeks[0].HolidayHours.Equal(dec("8")) {
		t.Errorf("week of the 16th = %+v, want 16 h after 16 h leave and 8 h holiday", w.Weeks[0])
	}
	if w.Weeks[1].WeekStart != "2026-11-23" || !w.Weeks[1].Hours.Equal(dec("40")) {
		t.Errorf("week of the 23rd = %+v, want 40 h (pending leave and another tenant's holiday do not count)", w.Weeks[1])
	}
	for i, wantEmployee := range map[int]bool{1: true, 2: false, 3: false, 4: false, 5: false} {
		p := got[i]
		if p.Configured || p.HasEmployee != wantEmployee || len(p.Weeks) != 0 || !p.WeeklyHours.IsZero() {
			t.Errorf("row %d (%s) = %+v, want unconfigured with has_employee %v", i, p.AuthUserID, p, wantEmployee)
		}
	}

	if _, err := NewService(client).Capacity(ctx, tenant, ids, day("2026-11-24"), day("2026-11-18")); err != ErrCapacityRange {
		t.Errorf("to before from = %v, want ErrCapacityRange", err)
	}
	if _, err := NewService(client).Capacity(ctx, tenant, ids, day("2026-01-01"), day("2027-06-01")); err != ErrCapacityRange {
		t.Errorf("a range over 366 days = %v, want ErrCapacityRange", err)
	}
}
