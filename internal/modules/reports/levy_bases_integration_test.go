package reports

import (
	"context"
	"testing"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Each return shows the base its own levy was charged on (stored on the payslip's levy line by the
// run), falling back to gross pay for payslips run before bases were stored. The Housing Levy
// employer share is the run's employer line, falling back to the employee share.
func TestIntegration_ReturnsShowLevyBases(t *testing.T) {
	fx := newReturnsFixture(t)
	ctx := context.Background()
	d := decimal.RequireFromString
	line := func(p *ent.Payslip, section, code, taxable, employer string) {
		fx.client.PayslipLine.Create().SetTenantID(fx.tenant).SetPayslipID(p.ID).SetSection(section).SetCode(code).SetLabel(code).
			SetCashAmount(d("1")).SetTaxableAmount(d(taxable)).SetEmployerAmount(d(employer)).SaveX(ctx)
	}
	// Amina, October: gross 50,000; a 10,000 allowance is outside NSSF, SHIF and AHL.
	line(fx.octA, "deduction_before_tax", "nssf_t1", "40000", "0")
	line(fx.octA, "deduction_before_tax", "shif", "40000", "0")
	line(fx.octA, "deduction_before_tax", "housing_levy", "40000", "0")
	line(fx.octA, "employer_contribution", "housing_levy_employer", "0", "600")
	// Brian has no stored bases (an older run).
	svc := NewService(fx.client)
	pick := func(rows []map[string]any, name string) map[string]any {
		for _, r := range rows {
			if r["employee_name"] == name {
				return r
			}
		}
		t.Fatalf("no row for %s in %v", name, rows)
		return nil
	}

	nssf, err := svc.NSSF(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if r := pick(nssf.Rows, "Amina Otieno"); r["pensionable_earnings"] != "40000.00" || r["gross_pay"] != "50000.00" {
		t.Errorf("nssf amina = %v", r)
	}
	if r := pick(nssf.Rows, "Brian"); r["pensionable_earnings"] != "30000.00" {
		t.Errorf("nssf brian fallback = %v", r)
	}

	shif, err := svc.SHIF(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	if r := pick(shif.Rows, "Amina Otieno"); r["gross_salary"] != "40000.00" {
		t.Errorf("shif amina = %v", r)
	}

	ahl, err := svc.HousingLevy(ctx, fx.tenant, fx.octF)
	if err != nil {
		t.Fatal(err)
	}
	a := pick(ahl.Rows, "Amina Otieno")
	if a["gross_salary"] != "40000.00" || a["employee_levy"] != "750.00" || a["employer_levy"] != "600.00" || a["total_levy"] != "1350.00" {
		t.Errorf("ahl amina = %v", a)
	}
	if b := pick(ahl.Rows, "Brian"); b["gross_salary"] != "30000.00" || b["employer_levy"] != "450.00" {
		t.Errorf("ahl brian fallback = %v", b)
	}

	year, err := ResolvePeriod(2026, 0, nil)
	if err != nil {
		t.Fatal(err)
	}
	p10, err := svc.P10(ctx, fx.tenant, year)
	if err != nil {
		t.Fatal(err)
	}
	var m ReportSheet
	for _, s := range p10.Sheets {
		if s.Name == "Sheet M - AHL" {
			m = s
		}
	}
	if r := pick(m.Rows, "Amina Otieno"); r["gross_salary"] != "80000.00" || r["employer_ahl"] != "1200.00" {
		// September (no stored base: gross 40,000, employer = employee 600) plus October (40,000, employer 600).
		t.Errorf("sheet M amina = %v", r)
	}
}
