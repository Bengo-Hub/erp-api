package payroll

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// The pay summary lists what a run applies, with the run's amounts and nothing persisted: the
// golden master for a 100,000 salary, a loan, an assigned item, and a statutory switch.
func TestIntegration_EmployeePaySummary(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	d := decimal.RequireFromString
	set := payrollsettings.NewService(client, uuid.New())
	seedPlatformPayroll(t, ctx, client, set)
	svc := NewService(client, set)
	tenant := uuid.New()
	sep := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)

	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Waiter").SaveX(ctx)
	byCode := func(s *PaySummary) map[string]PaySummaryLine {
		m := map[string]PaySummaryLine{}
		for _, l := range s.Lines {
			m[l.Code] = l
		}
		return m
	}

	// No salary: said so, statutory items listed without amounts.
	s, err := svc.EmployeePaySummary(ctx, tenant, emp.ID, sep)
	if err != nil || s.State != PaySummaryNoSalary || s.Net != nil {
		t.Fatalf("no salary = %+v %v", s, err)
	}
	if l, ok := byCode(s)["paye"]; !ok || l.Employee != nil || l.Origin != OriginStatutory {
		t.Errorf("PAYE without a salary = %+v, want listed with no amount", l)
	}

	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetMonthlySalary(d("100000")).SaveX(ctx)
	client.EmployeeLoan.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetIsActive(true).
		SetPrincipalAmount(d("5000")).SetMonthlyInstallment(d("1000")).SaveX(ctx)
	s, err = svc.EmployeePaySummary(ctx, tenant, emp.ID, sep)
	if err != nil || s.State != PaySummaryOK || !s.Net.Equal(d("70617.65")) {
		t.Fatalf("summary = %+v %v, want net 70617.65", s, err)
	}
	for code, want := range map[string]struct{ origin, employee, employer string }{
		"basic": {OriginAutomatic, "100000", ""}, "paye": {OriginStatutory, "19812.35", ""},
		"nssf_t1": {OriginStatutory, "480", ""}, "nssf_t2": {OriginStatutory, "3840", ""},
		"shif": {OriginStatutory, "2750", ""}, "housing_levy": {OriginStatutory, "1500", ""},
		"personal_relief": {OriginStatutory, "2400", ""}, "loan": {OriginAutomatic, "1000", ""},
		"nssf_employer": {OriginStatutory, "", "4320"}, "housing_levy_employer": {OriginStatutory, "", "1500"},
	} {
		l, ok := byCode(s)[code]
		if !ok || l.Origin != want.origin ||
			(want.employee != "" && (l.Employee == nil || !l.Employee.Equal(d(want.employee)))) ||
			(want.employer != "" && (l.Employer == nil || !l.Employer.Equal(d(want.employer)))) {
			t.Errorf("%s = %+v, want %+v", code, l, want)
		}
	}
	if n := client.Payslip.Query().Where(payslip.TenantID(tenant)).CountX(ctx); n != 0 {
		t.Errorf("the summary stored %d payslips", n)
	}

	// The organisation's statutory switch shows as off; the person's exemption is noted.
	client.GeneralHRSettings.Create().SetTenantID(tenant).SetShifEnabled(false).SaveX(ctx)
	client.SalaryDetails.Update().SetDisabilityExempt(true).ExecX(ctx)
	s, err = svc.EmployeePaySummary(ctx, tenant, emp.ID, sep)
	if err != nil {
		t.Fatal(err)
	}
	if l := byCode(s)["shif"]; !l.Off || l.Employee != nil {
		t.Errorf("SHIF switched off = %+v", l)
	}
	if len(s.Notes) != 1 {
		t.Errorf("notes = %v, want the exemption", s.Notes)
	}

	if _, err := svc.EmployeePaySummary(ctx, uuid.New(), emp.ID, sep); !ent.IsNotFound(err) {
		t.Errorf("another tenant = %v, want not found", err)
	}
}
