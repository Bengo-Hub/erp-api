package payroll

import (
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// AmountItem is a labelled money figure on a payslip breakdown (earnings/deductions row).
type AmountItem struct {
	Label  string
	Amount decimal.Decimal
}

// PayslipBreakdown is the single source of truth for the figures shown on a payslip,
// shared by the JSON payslip view AND the PDF document adapter so the two never drift.
// All amounts are decimals; the caller formats for its surface.
type PayslipBreakdown struct {
	GrossPay        decimal.Decimal
	BasicSalary     decimal.Decimal // gross is treated as basic+allowances aggregate (legacy parity)
	TotalEarnings   decimal.Decimal
	PAYE            decimal.Decimal
	NSSF            decimal.Decimal // employee tiers 1+2
	SHIF            decimal.Decimal // SHIF/NHIF
	HousingLevy     decimal.Decimal
	OtherDeductions decimal.Decimal // anything in (gross - net) not covered by the statutory rows
	TotalDeductions decimal.Decimal // gross - net
	NetPay          decimal.Decimal

	Earnings   []AmountItem // ordered earnings rows for the two-column payslip layout
	Deductions []AmountItem // ordered deduction rows (statutory + other)
}

// BuildPayslipBreakdown derives the earnings/deductions/net figures from a stored
// payslip. It is the ONE place that decides how net pay decomposes, so the JSON view
// and the PDF render identical numbers. Statutory deductions come from the dedicated
// columns; any residual (gross - net - statutory) is grouped under "Other Deductions"
// so the deduction column always sums exactly to (gross - net).
func BuildPayslipBreakdown(ps *ent.Payslip) PayslipBreakdown {
	nssf := ps.NssfEmployeeTier1.Add(ps.NssfEmployeeTier2)
	totalDeductions := ps.GrossPay.Sub(ps.NetPay)

	statutory := ps.Paye.Add(nssf).Add(ps.ShifOrNhifContribution).Add(ps.HousingLevy)
	other := totalDeductions.Sub(statutory)
	if other.IsNegative() {
		other = decimal.Zero
	}

	b := PayslipBreakdown{
		GrossPay:        ps.GrossPay,
		BasicSalary:     ps.GrossPay,
		TotalEarnings:   ps.GrossPay,
		PAYE:            ps.Paye,
		NSSF:            nssf,
		SHIF:            ps.ShifOrNhifContribution,
		HousingLevy:     ps.HousingLevy,
		OtherDeductions: other,
		TotalDeductions: totalDeductions,
		NetPay:          ps.NetPay,
	}

	b.Earnings = []AmountItem{
		{Label: "Gross Pay", Amount: ps.GrossPay},
	}
	b.Deductions = []AmountItem{
		{Label: "PAYE", Amount: ps.Paye},
		{Label: "NSSF", Amount: nssf},
		{Label: "SHIF / NHIF", Amount: ps.ShifOrNhifContribution},
		{Label: "Housing Levy", Amount: ps.HousingLevy},
	}
	if other.IsPositive() {
		b.Deductions = append(b.Deductions, AmountItem{Label: "Other Deductions", Amount: other})
	}
	return b
}

// BuildPayslipBreakdownWithLines is BuildPayslipBreakdown but, when itemised payslip_line rows
// exist (new runs), it replaces the lumped "Gross Pay" earning + the 4 statutory deduction rows
// with the real per-component lines (Basic Pay, House Allowance, N.S.S.F. Tier I/II, Loan, …).
// Falls back to the aggregate breakdown when there are no lines (old payslips). The scalar
// fields (PAYE/NSSF/Net…) are always the stored totals so existing consumers are unchanged.
func BuildPayslipBreakdownWithLines(ps *ent.Payslip, lines []*ent.PayslipLine) PayslipBreakdown {
	b := BuildPayslipBreakdown(ps)
	if len(lines) == 0 {
		return b
	}
	earnings := make([]AmountItem, 0, len(lines))
	deductions := make([]AmountItem, 0, len(lines))
	for _, l := range lines {
		switch l.Section {
		case "earning_cash", "benefit_noncash":
			earnings = append(earnings, AmountItem{Label: l.Label, Amount: l.CashAmount})
		case "deduction_before_tax", "tax", "deduction_after_tax":
			// relief + employer_contribution are intentionally excluded (relief reduces PAYE; the
			// employer side is not deducted from the employee's net).
			deductions = append(deductions, AmountItem{Label: l.Label, Amount: l.CashAmount})
		}
	}
	if len(earnings) > 0 {
		b.Earnings = earnings
	}
	if len(deductions) > 0 {
		b.Deductions = deductions
	}
	return b
}
