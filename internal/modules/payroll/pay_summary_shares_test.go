package payroll

import (
	"testing"

	"github.com/shopspring/decimal"
)

// TestAttachEmployerShares: a shared deduction reads across one row (employee and employer), the
// separate employer rows are dropped (the Housing Levy one was listed twice), and an employer
// share whose deduction row is missing keeps its own row.
func TestAttachEmployerShares(t *testing.T) {
	d := decimal.RequireFromString
	p := func(s string) *decimal.Decimal { v := d(s); return &v }
	sum := PaySummary{Lines: []PaySummaryLine{
		{Code: "basic", Kind: "earning", Employee: p("50000")},
		{Code: "nssf_t1", Kind: "deduction", Employee: p("540")},
		{Code: "nssf_t2", Kind: "deduction", Employee: p("2460")},
		{Code: "housing_levy", Kind: "deduction", Employee: p("750")},
		{Code: "nssf_employer", Kind: "employer", Employer: p("3000")},
		{Code: "housing_levy_employer", Kind: "employer", Employer: p("750")},
		{Code: "nita", Kind: "employer", Employer: p("50")},
	}}
	sum.attachEmployerShares(d("540"), d("2460"), d("3000"), d("750"))

	got := map[string]PaySummaryLine{}
	for _, l := range sum.Lines {
		if _, dup := got[l.Code]; dup {
			t.Fatalf("%s listed twice", l.Code)
		}
		got[l.Code] = l
	}
	for code, want := range map[string]string{"nssf_t1": "540", "nssf_t2": "2460", "housing_levy": "750", "nita": "50"} {
		l, ok := got[code]
		if !ok || l.Employer == nil || !l.Employer.Equal(d(want)) {
			t.Errorf("%s employer = %v, want %s", code, l.Employer, want)
		}
	}
	for _, code := range []string{"nssf_employer", "housing_levy_employer"} {
		if _, ok := got[code]; ok {
			t.Errorf("%s should be merged into its deduction row", code)
		}
	}

	// No Housing Levy row (switched off or not charged): the employer share keeps its own row.
	alone := PaySummary{Lines: []PaySummaryLine{{Code: "nssf_t1", Kind: "deduction", Employee: p("540")}}}
	alone.attachEmployerShares(d("540"), decimal.Zero, d("540"), d("750"))
	if len(alone.Lines) != 2 || alone.Lines[0].Employer == nil || !alone.Lines[0].Employer.Equal(d("540")) || alone.Lines[1].Code != "housing_levy_employer" {
		t.Errorf("alone = %+v", alone.Lines)
	}
}
