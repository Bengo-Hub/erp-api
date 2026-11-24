package reports

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// returnsFixture is two employees paid in September and October 2026, plus a payslip of
// another tenant that no report may show.
type returnsFixture struct {
	client       *ent.Client
	tenant       uuid.UUID
	amina, brian *ent.Employee
	octA, octB   *ent.Payslip
	oct, sep     time.Time
	octF         Filter
}

func newReturnsFixture(t *testing.T) *returnsFixture {
	t.Helper()
	client := analyticsClient(t)
	ctx := context.Background()
	d := decimal.RequireFromString
	fx := &returnsFixture{
		client: client,
		tenant: uuid.New(),
		oct:    time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC),
		sep:    time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC),
	}
	fx.amina = client.Employee.Create().SetTenantID(fx.tenant).SetFirstName("Amina").SetLastName("Otieno").
		SetPinNo("A001").SetNssfNo("N-1").SetShifOrNhifNumber("SHA-1").SetEmployeeNumber("E1").SaveX(ctx)
	fx.brian = client.Employee.Create().SetTenantID(fx.tenant).SetFirstName("Brian").SetPinNo("B002").SaveX(ctx)

	slip := func(tenant, emp uuid.UUID, period time.Time, gross, net string) *ent.Payslip {
		return client.Payslip.Create().SetTenantID(tenant).SetEmployeeID(emp).SetPaymentPeriod(period).
			SetGrossPay(d(gross)).SetNetPay(d(net)).SetPaye(d("1000")).
			SetNssfEmployeeTier1(d("540")).SetNssfEmployeeTier2(d("660")).SetNssfEmployerContribution(d("1200")).
			SetShifOrNhifContribution(d(gross).Mul(d("0.0275")).Round(2)).SetHousingLevy(d(gross).Mul(d("0.015")).Round(2)).
			SaveX(ctx)
	}
	fx.octA = slip(fx.tenant, fx.amina.ID, fx.oct, "50000", "40000")
	fx.octB = slip(fx.tenant, fx.brian.ID, fx.oct, "30000", "25000")
	slip(fx.tenant, fx.amina.ID, fx.sep, "40000", "32000")
	slip(uuid.New(), fx.amina.ID, fx.oct, "99999", "99999")

	f, err := ResolvePeriod(2026, 10, nil)
	if err != nil {
		t.Fatal(err)
	}
	fx.octF = f
	return fx
}

// assertKeys fails when a row lacks any of the keys the erp-ui report page reads.
func assertKeys(t *testing.T, what string, row map[string]any, keys ...string) {
	t.Helper()
	for _, k := range keys {
		if _, ok := row[k]; !ok {
			t.Fatalf("%s row has no %q: %v", what, k, row)
		}
	}
}

func TestIntegration_NSSFReturnFields(t *testing.T) {
	fx := newReturnsFixture(t)
	rep, err := NewService(fx.client).NSSF(context.Background(), fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 2 {
		t.Fatalf("rows = %v", rep.Rows)
	}
	r := rep.Rows[0]
	if r["employee_name"] == "Brian" {
		r = rep.Rows[1]
	}
	assertKeys(t, "nssf", r, nssfColumns...)
	if r["employee_name"] != "Amina Otieno" || r["employee_pin"] != "A001" || r["nssf_number"] != "N-1" ||
		r["gross_pay"] != "50000.00" || r["employee_total"] != "1200.00" || r["employer"] != "1200.00" ||
		r["nssf_contribution"] != "2400.00" {
		t.Fatalf("nssf row = %v", r)
	}
	if rep.Totals["nssf_contribution"] != "4800.00" || rep.Totals["employee_total"] != "2400.00" || rep.Totals["count"] != 2 {
		t.Fatalf("nssf totals = %v", rep.Totals)
	}
}

// A department filter narrows a payroll return to that department's employees (hr_details).
func TestIntegration_ReturnDepartmentFilter(t *testing.T) {
	fx := newReturnsFixture(t)
	ctx := context.Background()
	dept := fx.client.Department.Create().SetTenantID(fx.tenant).SetTitle("Finance").SaveX(ctx)
	other := fx.client.Department.Create().SetTenantID(fx.tenant).SetTitle("Sales").SaveX(ctx)
	fx.client.HRDetails.Create().SetTenantID(fx.tenant).SetEmployeeID(fx.amina.ID).SetDepartmentID(dept.ID).SaveX(ctx)
	fx.client.HRDetails.Create().SetTenantID(fx.tenant).SetEmployeeID(fx.brian.ID).SetDepartmentID(other.ID).SaveX(ctx)

	f := fx.octF
	f.DepartmentID = &dept.ID
	rep, err := NewService(fx.client).NSSF(ctx, fx.tenant, f)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 1 || rep.Rows[0]["employee_name"] != "Amina Otieno" || rep.Totals["count"] != 1 {
		t.Fatalf("finance-only NSSF = rows %v totals %v", rep.Rows, rep.Totals)
	}
	empty := uuid.New()
	f.DepartmentID = &empty
	if rep, err = NewService(fx.client).NSSF(ctx, fx.tenant, f); err != nil || len(rep.Rows) != 0 {
		t.Fatalf("unknown department must return no rows, got %v (%v)", rep.Rows, err)
	}
}

func TestIntegration_NHIFReturnFields(t *testing.T) {
	fx := newReturnsFixture(t)
	rep, err := NewService(fx.client).NHIF(context.Background(), fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 2 {
		t.Fatalf("rows = %v", rep.Rows)
	}
	r := rep.Rows[0]
	if r["employee_name"] == "Brian" {
		r = rep.Rows[1]
	}
	assertKeys(t, "nhif", r, "employee_name", "employee_pin", "nhif_number", "nhif_contribution", "coverage_type")
	if r["nhif_number"] != "SHA-1" || r["nhif_contribution"] != "1375.00" || r["coverage_type"] != "SHIF" || r["gross_pay"] != "50000.00" {
		t.Fatalf("nhif row = %v", r)
	}
	if rep.Totals["nhif_contribution"] != "2200.00" {
		t.Fatalf("nhif totals = %v", rep.Totals)
	}
}

func TestIntegration_NITAReturn(t *testing.T) {
	fx := newReturnsFixture(t)
	ctx := context.Background()
	// Amina's payslip carries the itemised levy the run charged; Brian's predates the line and
	// gets the configured levy (no tenant formula here, so the national default of 50).
	fx.client.PayslipLine.Create().SetTenantID(fx.tenant).SetPayslipID(fx.octA.ID).SetSection("employer_contribution").
		SetCode("nita").SetLabel("NITA Levy").SetEmployerAmount(decimal.RequireFromString("50")).SaveX(ctx)

	rep, err := NewService(fx.client).NITA(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 2 {
		t.Fatalf("rows = %v, want one per payslip", rep.Rows)
	}
	for _, r := range rep.Rows {
		assertKeys(t, "nita", r, nitaColumns...)
		if r["nita_levy"] != "50.00" {
			t.Fatalf("nita row = %v", r)
		}
	}
	if rep.Totals["nita_levy"] != "100.00" || rep.Totals["count"] != 2 {
		t.Fatalf("nita totals = %v", rep.Totals)
	}

	// With NITA switched off, only the levy a run actually charged stays on the return.
	fx.client.GeneralHRSettings.Create().SetTenantID(fx.tenant).SetNitaEnabled(false).SaveX(ctx)
	rep, err = NewService(fx.client).NITA(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 1 || rep.Rows[0]["employee_name"] != "Amina Otieno" || rep.Totals["nita_levy"] != "50.00" {
		t.Fatalf("disabled nita = %v totals %v", rep.Rows, rep.Totals)
	}
}

func TestIntegration_BankScheduleGroupsByBank(t *testing.T) {
	fx := newReturnsFixture(t)
	ctx := context.Background()
	fx.client.EmployeeBankAccount.Create().SetTenantID(fx.tenant).SetEmployeeID(fx.amina.ID).SetBankName("KCB").
		SetBankCode("01").SetAccountName("Amina Otieno").SetAccountNumber("111").SetIsPrimary(true).SaveX(ctx)

	rep, err := NewService(fx.client).BankSchedule(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 2 {
		t.Fatalf("rows = %v, want KCB and the no-account group", rep.Rows)
	}
	kcb, none := rep.Rows[0], rep.Rows[1]
	assertKeys(t, "bank", kcb, bankColumns...)
	if kcb["bank_name"] != "KCB" || kcb["employee_count"] != 1 || kcb["account_count"] != 1 ||
		kcb["total_net_pay"] != "40000.00" || kcb["reference_number"] != "NET-202610-01" {
		t.Fatalf("kcb row = %v", kcb)
	}
	if none["bank_name"] != noBankAccount || none["total_net_pay"] != "25000.00" || none["account_count"] != 0 {
		t.Fatalf("no-account row = %v", none)
	}
	if rep.Totals["total_net_pay"] != "65000.00" {
		t.Fatalf("bank totals = %v", rep.Totals)
	}
	if len(rep.Sheets) != 2 || len(rep.Sheets[1].Rows) != 2 || rep.Sheets[1].Rows[0]["account_number"] != "111" {
		t.Fatalf("bank sheets = %v", rep.Sheets)
	}
}

func TestIntegration_PayrollVarianceByCategory(t *testing.T) {
	fx := newReturnsFixture(t)
	rep, err := NewService(fx.client).PayrollVariance(context.Background(), fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	byCat := map[string]map[string]any{}
	for _, r := range rep.Rows {
		assertKeys(t, "variance", r, varianceColumns...)
		byCat[r["variance_category"].(string)] = r
	}
	net := byCat["Net Pay"]
	if net == nil || net["current_period"] != "65000.00" || net["previous_period"] != "32000.00" ||
		net["variance_amount"] != "33000.00" || net["variance_percent"] != "103.13" || net["variance_type"] != "Increase" {
		t.Fatalf("net pay row = %v", net)
	}
	gross := byCat["Gross Pay"]
	if gross == nil || gross["current_period"] != "80000.00" || gross["previous_period"] != "40000.00" {
		t.Fatalf("gross row = %v", gross)
	}
	if rep.Totals["current_headcount"] != 2 || rep.Totals["previous_headcount"] != 1 || rep.Totals["previous_start"] != "2026-09-01" {
		t.Fatalf("variance totals = %v", rep.Totals)
	}
}
