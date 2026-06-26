package payroll

import (
	"testing"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

func dec(s string) decimal.Decimal { return decimal.RequireFromString(s) }

// TestBuildPayslipBreakdownWithLines: when lines exist they drive the earnings/deductions rows
// (relief + employer contributions are excluded from the deduction column); with no lines it
// falls back to the aggregate "Gross Pay" + 4 statutory rows.
func TestBuildPayslipBreakdownWithLines(t *testing.T) {
	ps := &ent.Payslip{
		GrossPay: dec("81000"), NetPay: dec("52425.40"), Paye: dec("16687.10"),
		ShifOrNhifContribution: dec("2227.50"), HousingLevy: dec("0"),
		NssfEmployeeTier1: dec("480"), NssfEmployeeTier2: dec("1680"),
	}

	// Fallback (no lines): single Gross Pay earning row.
	agg := BuildPayslipBreakdownWithLines(ps, nil)
	if len(agg.Earnings) != 1 || agg.Earnings[0].Label != "Gross Pay" {
		t.Fatalf("fallback earnings = %+v, want single Gross Pay", agg.Earnings)
	}

	// With lines: itemised earnings; relief + employer excluded from deductions.
	lines := []*ent.PayslipLine{
		{Section: "earning_cash", Label: "Basic Pay", CashAmount: dec("76000")},
		{Section: "benefit_noncash", Label: "House Allowance", CashAmount: dec("5000")},
		{Section: "deduction_before_tax", Label: "S.H.I.F.", CashAmount: dec("2227.50")},
		{Section: "relief", Label: "Personal Relief", CashAmount: dec("2400")},
		{Section: "tax", Label: "P.A.Y.E.", CashAmount: dec("16687.10")},
		{Section: "deduction_after_tax", Label: "Loan", CashAmount: dec("2840")},
		{Section: "employer_contribution", Label: "N.S.S.F. Employer", EmployerAmount: dec("2160")},
	}
	b := BuildPayslipBreakdownWithLines(ps, lines)
	if len(b.Earnings) != 2 {
		t.Errorf("earnings = %d, want 2 (Basic + House Allowance)", len(b.Earnings))
	}
	// deductions = SHIF + PAYE + Loan (NOT relief, NOT employer).
	if len(b.Deductions) != 3 {
		t.Errorf("deductions = %d, want 3 (SHIF, PAYE, Loan)", len(b.Deductions))
	}
	for _, d := range b.Deductions {
		if d.Label == "Personal Relief" || d.Label == "N.S.S.F. Employer" {
			t.Errorf("deduction column must not include %q", d.Label)
		}
	}
	// Scalar totals always come from the stored payslip.
	if !b.NetPay.Equal(dec("52425.40")) {
		t.Errorf("net pay = %s, want 52425.40", b.NetPay)
	}
}
