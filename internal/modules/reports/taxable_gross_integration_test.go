package reports

import (
	"context"
	"testing"

	"github.com/shopspring/decimal"
)

// KRA PAYE returns declare taxable gross: a non-taxable earning (per diem) in the stored payslip
// lines is left out of P9, P9A, P10 and P10A, while the payslip's own gross and the other returns
// are unchanged. A payslip without such a line keeps its gross.
func TestIntegration_TaxableGrossOnPAYEReturns(t *testing.T) {
	fx := newReturnsFixture(t)
	ctx := context.Background()
	d := decimal.RequireFromString
	line := func(label, amount string, taxable bool) {
		fx.client.PayslipLine.Create().SetTenantID(fx.tenant).SetPayslipID(fx.octA.ID).SetSection("earning_cash").
			SetLabel(label).SetCashAmount(d(amount)).SetTaxable(taxable).SaveX(ctx)
	}
	line("Basic Pay", "45000", true)
	line("Per Diem", "5000", false)
	svc := NewService(fx.client)

	rowOf := func(rows []map[string]any) map[string]any {
		t.Helper()
		for _, r := range rows {
			if r["employee_pin"] == "A001" {
				return r
			}
		}
		t.Fatal("no row for A001")
		return nil
	}
	p9, err := svc.P9(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if r := rowOf(p9.Rows); r["total_gross_pay"] != "45000.00" || r["total_deductions"] != "10000.00" || r["net_pay"] != "40000.00" {
		t.Errorf("P9 row = %v, want gross 45000, deductions 10000, net 40000", r)
	}
	for _, r := range p9.Rows {
		if r["employee_pin"] == "B002" && r["total_gross_pay"] != "30000.00" {
			t.Errorf("P9 gross without non-taxable lines = %v, want 30000", r["total_gross_pay"])
		}
	}
	p9a, err := svc.P9A(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if r := rowOf(p9a.Rows); r["total_gross_pay"] != "45000.00" {
		t.Errorf("P9A gross = %v, want 45000", r["total_gross_pay"])
	}
	p10a, err := svc.P10A(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if r := rowOf(p10a.Rows); r["total_gross_pay"] != "45000.00" {
		t.Errorf("P10A gross = %v, want 45000", r["total_gross_pay"])
	}
	p10, err := svc.P10(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if r := rowOf(p10.Rows); r["gross_pay"] != "45000.00" {
		t.Errorf("P10 gross = %v, want 45000", r["gross_pay"])
	}
	if r := rowOf(p10.Sheets[2].Rows); r["gross_salary"] != "50000.00" {
		t.Errorf("P10 sheet M gross salary = %v, want the payslip gross 50000 (no stored levy base)", r["gross_salary"])
	}
	nssf, err := svc.NSSF(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if r := rowOf(nssf.Rows); r["gross_pay"] != "50000.00" {
		t.Errorf("NSSF gross = %v, want the payslip gross 50000", r["gross_pay"])
	}
}
