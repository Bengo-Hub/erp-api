package payroll

import (
	"testing"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// The breakdown carries each statutory deduction, the employer side, loan recoveries by the loan
// type's account, staff purchases without one, and check-offs with the component's account; it is
// left out when it would place more than was withheld. The currency is the tenant's.
func TestIntegration_GLBreakdown(t *testing.T) {
	f := newDisburseFixture(t)
	ctx, c := f.context, f.client
	dec := decimal.RequireFromString
	c.CompanySettings.Create().SetTenantID(f.tenant).SetDefaultCurrency("ugx").SaveX(ctx)
	s0 := c.Payslip.UpdateOne(f.slips[0]).SetPaye(dec("5000")).SetNssfEmployeeTier1(dec("540")).SetNssfEmployeeTier2(dec("2460")).
		SetShifOrNhifContribution(dec("1375")).SetHousingLevy(dec("750")).SaveX(ctx)
	lt := c.LoanType.Create().SetTenantID(f.tenant).SetTitle("Staff loan").SetAccountCode("1425").SaveX(ctx)
	loan := c.EmployeeLoan.Create().SetTenantID(f.tenant).SetEmployeeID(s0.EmployeeID).SetLoanTypeID(lt.ID).
		SetPrincipalAmount(dec("10000")).SetMonthlyInstallment(dec("100")).SaveX(ctx)
	sacco := c.PayrollComponent.Create().SetTenantID(f.tenant).SetTitle("SACCO").SetWbCode("sacco").SetAccCode("2545").SaveX(ctx)
	line := func(section, code string, cash, employer string, comp *ent.PayrollComponent) {
		b := c.PayslipLine.Create().SetTenantID(f.tenant).SetPayslipID(s0.ID).SetSection(section).SetCode(code).SetLabel(code).
			SetCashAmount(dec(cash)).SetEmployerAmount(dec(employer))
		if comp != nil {
			b = b.SetComponentID(comp.ID)
		}
		b.SaveX(ctx)
	}
	line(secEmployer, "nssf_employer", "0", "3000", nil)
	line(secEmployer, "housing_levy_employer", "0", "750", nil)
	line(secEmployer, "nita", "0", "50", nil)
	line(secAfterPaye, "loan", "100", "0", nil)
	line(secAfterPaye, "staff_purchase", "200", "0", nil)
	line(secAfterPaye, "sacco", "300", "0", sacco)
	c.RecoveryLine.Create().SetTenantID(f.tenant).SetPayslipID(s0.ID).SetEmployeeID(s0.EmployeeID).
		SetRecoverableType("loan").SetRecoverableID(loan.ID).SetAmount(dec("100")).SaveX(ctx)

	slips := []*ent.Payslip{s0, f.slips[1]}
	bd, err := f.d.buildBreakdown(ctx, f.tenant, slips, dec("20000"))
	if err != nil || bd == nil {
		t.Fatalf("breakdown = %v, %v", bd, err)
	}
	emp, er := bd["employee"].(map[string]any), bd["employer"].(map[string]any)
	if emp["paye"] != "5000.00" || emp["nssf"] != "3000.00" || emp["shif"] != "1375.00" || emp["housing_levy"] != "750.00" {
		t.Errorf("employee = %v", emp)
	}
	if er["nssf"] != "3000.00" || er["housing_levy"] != "750.00" || er["nita"] != "50.00" {
		t.Errorf("employer = %v", er)
	}
	recs := map[string]map[string]any{}
	for _, r := range bd["recoveries"].([]map[string]any) {
		recs[r["type"].(string)] = r
	}
	if recs["loan"]["account_code"] != "1425" || recs["loan"]["amount"] != "100.00" || recs["staff_purchase"]["amount"] != "200.00" {
		t.Errorf("recoveries = %v", recs)
	}
	others := bd["other_deductions"].([]map[string]any)
	if len(others) != 1 || others[0]["account_code"] != "2545" || others[0]["amount"] != "300.00" {
		t.Errorf("other deductions = %v", others)
	}
	if again, _ := f.d.buildBreakdown(ctx, f.tenant, slips, dec("1000")); again != nil {
		t.Error("a breakdown above the withheld amount must be left out")
	}
	if cur := f.d.tenantCurrency(ctx, f.tenant); cur != "UGX" {
		t.Errorf("currency %s, want UGX", cur)
	}
}
