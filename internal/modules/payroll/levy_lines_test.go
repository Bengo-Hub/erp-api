package payroll

import (
	"testing"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// The payslip's levy lines carry the pay each levy was charged on, and the employer Housing Levy
// has its own line, so the statutory returns can show them.
func TestLevyLinesCarryTheirBases(t *testing.T) {
	d := decimal.RequireFromString
	res := payrollengine.PayslipResult{
		GrossPay: d("60000"), TaxablePay: d("53850"), PAYE: d("8538.35"),
		NSSFEmployeeTier1: d("540"), NSSFEmployeeTier2: d("2460"), NSSFBase: d("50000"),
		SHIFOrNHIF: d("1375"), SHIFBase: d("50000"), HousingLevy: d("750"), HousingLevyBase: d("50000"),
		HousingLevyEmployer: d("750"),
	}
	got := map[string]ComposedLine{}
	for _, l := range composeLines(d("50000"), res, EmployeeItemized{}) {
		got[l.Code] = l
	}
	for code, want := range map[string]string{"nssf_t1": "50000", "shif": "50000", "housing_levy": "50000", "paye": "53850"} {
		if !got[code].TaxableAmount.Equal(d(want)) {
			t.Errorf("%s base %s, want %s", code, got[code].TaxableAmount, want)
		}
	}
	if !got["housing_levy_employer"].Employer.Equal(d("750")) {
		t.Errorf("employer housing levy line = %+v", got["housing_levy_employer"])
	}
}
