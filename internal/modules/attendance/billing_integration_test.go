package attendance

import (
	"context"
	"sort"
	"sync"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/timesheet"
)

type billingFixture struct {
	t        *testing.T
	ctx      context.Context
	client   *ent.Client
	svc      *Service
	tenant   uuid.UUID
	employee *ent.Employee
}

func newBillingFixture(t *testing.T) *billingFixture {
	client := testClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	emp, err := client.Employee.Create().SetTenantID(tenant).SetFirstName("Jane").SetLastName("Doe").Save(ctx)
	if err != nil {
		t.Fatal(err)
	}
	return &billingFixture{t: t, ctx: ctx, client: client, svc: NewService(client), tenant: tenant, employee: emp}
}

func day(s string) time.Time { d, _ := time.Parse(time.DateOnly, s); return d }

func (f *billingFixture) sheet(employee uuid.UUID, status timesheet.Status, start string) uuid.UUID {
	ts, err := f.client.Timesheet.Create().SetTenantID(f.tenant).SetEmployeeID(employee).
		SetPeriodStart(day(start)).SetPeriodEnd(day(start).AddDate(0, 0, 6)).SetStatus(status).Save(f.ctx)
	if err != nil {
		f.t.Fatal(err)
	}
	return ts.ID
}

func (f *billingFixture) entry(ts, project uuid.UUID, date string, billable bool, regular, overtime string) uuid.UUID {
	e, err := f.client.TimesheetEntry.Create().SetTenantID(f.tenant).SetTimesheetID(ts).SetProjectID(project).
		SetDate(day(date)).SetBillable(billable).SetTaskDescription("work on " + date).
		SetRegularHours(decimal.RequireFromString(regular)).SetOvertimeHours(decimal.RequireFromString(overtime)).
		Save(f.ctx)
	if err != nil {
		f.t.Fatal(err)
	}
	return e.ID
}

func ids(r *BillingReservation) []uuid.UUID {
	out := make([]uuid.UUID, len(r.Data))
	for i, e := range r.Data {
		out[i] = e.ID
	}
	sort.Slice(out, func(i, j int) bool { return out[i].String() < out[j].String() })
	return out
}

func sameIDs(a, b []uuid.UUID) bool {
	if len(a) != len(b) {
		return false
	}
	for i := range a {
		if a[i] != b[i] {
			return false
		}
	}
	return true
}

func TestIntegration_BillingReserveScope(t *testing.T) {
	f := newBillingFixture(t)
	project, other := uuid.New(), uuid.New()
	approved := f.sheet(f.employee.ID, timesheet.StatusApproved, "2026-11-02")
	submitted := f.sheet(f.employee.ID, timesheet.StatusSubmitted, "2026-11-09")

	in1 := f.entry(approved, project, "2026-11-02", true, "8", "1.5")
	in2 := f.entry(approved, project, "2026-11-08", true, "2", "0") // last day, inclusive
	f.entry(approved, project, "2026-11-03", false, "8", "0")       // not billable
	f.entry(approved, other, "2026-11-04", true, "8", "0")          // other project
	f.entry(approved, project, "2026-11-01", true, "8", "0")        // before the period (its sheet is approved too)
	f.entry(submitted, project, "2026-11-05", true, "8", "0")       // timesheet not approved

	ref := uuid.New()
	got, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-02"), day("2026-11-08"), ref)
	if err != nil {
		t.Fatal(err)
	}
	want := []uuid.UUID{in1, in2}
	sort.Slice(want, func(i, j int) bool { return want[i].String() < want[j].String() })
	if !sameIDs(ids(got), want) {
		t.Fatalf("reserved %v, want %v", ids(got), want)
	}
	if got.BilledInvoiceID != nil {
		t.Fatalf("billed_invoice_id = %v, want nil", *got.BilledInvoiceID)
	}
	first := got.Data[0]
	if first.Date != "2026-11-02" || first.EmployeeName != "Jane Doe" || first.EmployeeID != f.employee.ID ||
		!first.Hours.Equal(decimal.RequireFromString("9.5")) || first.Description != "work on 2026-11-02" || first.TaskID != nil {
		t.Fatalf("entry = %+v", first)
	}

	// A second run over the same period finds nothing left to bill.
	if again, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-01"), day("2026-11-30"), uuid.New()); err != nil {
		t.Fatal(err)
	} else if len(again.Data) != 1 || again.Data[0].Date != "2026-11-01" {
		t.Fatalf("second run reserved %+v, want only the 2026-11-01 entry", again.Data)
	}

	for _, p := range [][2]string{{"2026-11-08", "2026-11-02"}, {"2026-01-01", "2027-01-03"}} {
		if _, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day(p[0]), day(p[1]), uuid.New()); err != ErrBillingPeriod {
			t.Fatalf("period %v: err = %v, want ErrBillingPeriod", p, err)
		}
	}
}

func TestIntegration_BillingReserveRetryAndConcurrency(t *testing.T) {
	f := newBillingFixture(t)
	project := uuid.New()
	ts := f.sheet(f.employee.ID, timesheet.StatusApproved, "2026-11-02")
	a := f.entry(ts, project, "2026-11-02", true, "4", "0")

	ref := uuid.New()
	first, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-02"), day("2026-11-08"), ref)
	if err != nil {
		t.Fatal(err)
	}
	f.entry(ts, project, "2026-11-03", true, "3", "0")
	// The retry with the same ref returns the earlier entry and picks up the new one.
	second, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-02"), day("2026-11-08"), ref)
	if err != nil {
		t.Fatal(err)
	}
	if len(first.Data) != 1 || first.Data[0].ID != a || len(second.Data) != 2 {
		t.Fatalf("first %d entries, second %d, want 1 then 2", len(first.Data), len(second.Data))
	}

	// Concurrent runs under different refs never share an entry.
	c := f.entry(ts, project, "2026-11-04", true, "1", "0")
	const runs = 6
	var wg sync.WaitGroup
	results := make([]*BillingReservation, runs)
	errs := make([]error, runs)
	for i := 0; i < runs; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			results[i], errs[i] = f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-02"), day("2026-11-08"), uuid.New())
		}(i)
	}
	wg.Wait()
	winners := 0
	for i := range results {
		if errs[i] != nil {
			t.Fatal(errs[i])
		}
		for _, e := range results[i].Data {
			if e.ID != c {
				t.Fatalf("run %d got already reserved entry %s", i, e.ID)
			}
			winners++
		}
	}
	if winners != 1 {
		t.Fatalf("entry reserved %d times, want once", winners)
	}
}

func TestIntegration_BillingConfirmAndRelease(t *testing.T) {
	f := newBillingFixture(t)
	project := uuid.New()
	ts := f.sheet(f.employee.ID, timesheet.StatusApproved, "2026-11-02")
	f.entry(ts, project, "2026-11-02", true, "4", "0")
	f.entry(ts, project, "2026-11-03", true, "2", "0")

	ref, invoice, replacement := uuid.New(), uuid.New(), uuid.New()
	if _, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-02"), day("2026-11-08"), ref); err != nil {
		t.Fatal(err)
	}
	for i := 0; i < 2; i++ { // idempotent
		if n, err := f.svc.ConfirmBilling(f.ctx, f.tenant, ref, invoice); err != nil || n != 2 {
			t.Fatalf("confirm = %d, %v; want 2", n, err)
		}
	}
	// A deleted draft's entries are re-pointed at the next invoice for the same ref.
	if n, err := f.svc.ConfirmBilling(f.ctx, f.tenant, ref, replacement); err != nil || n != 2 {
		t.Fatalf("re-point = %d, %v; want 2", n, err)
	}
	got, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-02"), day("2026-11-08"), ref)
	if err != nil {
		t.Fatal(err)
	}
	if got.BilledInvoiceID == nil || *got.BilledInvoiceID != replacement.String() {
		t.Fatalf("billed_invoice_id = %v, want %s", got.BilledInvoiceID, replacement)
	}

	// A plain release frees nothing confirmed, but does free an unconfirmed entry under the ref.
	late := f.entry(ts, project, "2026-11-04", true, "1", "0")
	if _, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-02"), day("2026-11-08"), ref); err != nil {
		t.Fatal(err)
	}
	// The late entry was reserved after the confirmation, so it is the only one without an invoice.
	if n, err := f.svc.ReleaseBilling(f.ctx, f.tenant, ref, false); err != nil || n != 1 {
		t.Fatalf("release = %d, %v; want 1", n, err)
	}
	free, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-02"), day("2026-11-08"), uuid.New())
	if err != nil {
		t.Fatal(err)
	}
	if len(free.Data) != 1 || free.Data[0].ID != late {
		t.Fatalf("after release reserved %+v, want only the unconfirmed entry", free.Data)
	}

	// With include_confirmed (invoice void in treasury) the confirmed entries go back to the pool.
	if n, err := f.svc.ReleaseBilling(f.ctx, f.tenant, ref, true); err != nil || n != 2 {
		t.Fatalf("release confirmed = %d, %v; want 2", n, err)
	}
	rebill, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-02"), day("2026-11-08"), uuid.New())
	if err != nil {
		t.Fatal(err)
	}
	if len(rebill.Data) != 2 || rebill.BilledInvoiceID != nil {
		t.Fatalf("rebill = %d entries, invoice %v; want 2 and none", len(rebill.Data), rebill.BilledInvoiceID)
	}
}

func TestIntegration_ProjectHoursLabourCost(t *testing.T) {
	f := newBillingFixture(t)
	project := uuid.New()
	cheap, err := f.client.Employee.Create().SetTenantID(f.tenant).SetFirstName("No").SetLastName("Rate").Save(f.ctx)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := f.client.SalaryDetails.Create().SetTenantID(f.tenant).SetEmployeeID(f.employee.ID).
		SetHourlyRate(decimal.RequireFromString("500.25")).Save(f.ctx); err != nil {
		t.Fatal(err)
	}
	approved := f.sheet(f.employee.ID, timesheet.StatusApproved, "2026-11-02")
	noRate := f.sheet(cheap.ID, timesheet.StatusApproved, "2026-11-02")
	submitted := f.sheet(f.employee.ID, timesheet.StatusSubmitted, "2026-11-09")
	f.entry(approved, project, "2026-11-02", true, "8", "2")  // 10h billable
	f.entry(approved, project, "2026-11-03", false, "4", "0") // 4h not billable
	f.entry(noRate, project, "2026-11-02", true, "5", "0")    // 5h billable, no rate
	f.entry(submitted, project, "2026-11-09", true, "3", "0") // submitted, not costed
	reservedTS := f.sheet(f.employee.ID, timesheet.StatusApproved, "2026-11-16")
	f.entry(reservedTS, project, "2026-11-16", true, "1", "0") // billable, then reserved
	if _, err := f.svc.ReserveBillableEntries(f.ctx, f.tenant, project, day("2026-11-16"), day("2026-11-16"), uuid.New()); err != nil {
		t.Fatal(err)
	}

	got, err := f.svc.ProjectHours(f.ctx, f.tenant, []uuid.UUID{project, uuid.New()}, time.Time{}, time.Time{})
	if err != nil {
		t.Fatal(err)
	}
	p := got[0]
	// Approved: 10 + 4 + 5 + 1 = 20h; cost (10 + 4 + 1) x 500.25 = 7503.75; unbilled 10 + 5 = 15h.
	check := map[string][2]decimal.Decimal{
		"approved":  {p.ApprovedHours, decimal.RequireFromString("20")},
		"submitted": {p.SubmittedHours, decimal.RequireFromString("3")},
		"cost":      {p.LabourCost, decimal.RequireFromString("7503.75")},
		"unbilled":  {p.UnbilledBillableHours, decimal.RequireFromString("15")},
	}
	for k, v := range check {
		if !v[0].Equal(v[1]) {
			t.Errorf("%s = %s, want %s", k, v[0], v[1])
		}
	}
	if !got[1].LabourCost.IsZero() || !got[1].ApprovedHours.IsZero() {
		t.Errorf("idle project = %+v, want zeros", got[1])
	}
}
