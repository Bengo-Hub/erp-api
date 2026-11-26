package payroll

import (
	"time"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// PensionablePayFrom is the first payroll month whose pension deduction limit (30%, Income Tax Act
// s.22A) is taken on pensionable pay (basic, plus earnings flagged pensionable) instead of gross.
// Earlier months keep the gross base, so a re-run of a paid month does not change.
var PensionablePayFrom = time.Date(2026, 12, 1, 0, 0, 0, 0, time.UTC)

// pensionableFor is the pensionable pay the engine should use for a period: zero (the gross base)
// before PensionablePayFrom.
func pensionableFor(period time.Time, pensionable decimal.Decimal) decimal.Decimal {
	if period.Before(PensionablePayFrom) {
		return decimal.Zero
	}
	return pensionable
}

// countEarning applies an earning's levy flags to the engine input. inGross says whether the
// amount is part of gross pay (a taxable earning) or paid outside it (a tax-free one): a levy that
// leaves out an earning in gross lowers its base, a levy that counts an earning outside gross
// raises it. taxable is false for an amount the law exempts from PAYE whatever the flags say
// (the excluded part of a gratuity). A pensionable earning adds to pensionable pay.
func countEarning(in *payrollengine.EmployeeInput, f payrollsettings.LevyFlags, amt decimal.Decimal, inGross, taxable bool) {
	if !amt.IsPositive() {
		return
	}
	adj := func(dst *decimal.Decimal, counts bool) {
		switch {
		case inGross && !counts:
			*dst = dst.Sub(amt)
		case !inGross && counts:
			*dst = dst.Add(amt)
		}
	}
	adj(&in.LevyAdjust.NSSF, f.NSSF)
	adj(&in.LevyAdjust.SHIF, f.SHIF)
	adj(&in.LevyAdjust.HousingLevy, f.HousingLevy)
	adj(&in.LevyAdjust.PAYE, f.PAYE && taxable)
	if f.Pensionable {
		in.PensionablePay = in.PensionablePay.Add(amt)
	}
}
