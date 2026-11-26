package payroll

import (
	"time"

	"github.com/shopspring/decimal"
)

// Gratuity taxability (Income Tax Act, Cap. 470, as revised to 1 July 2026). A gratuity earning's
// component taxable_status picks the rule:
//   - "gratuity": s.5(4)(ga), from 1 July 2026. Gratuity on a contract of service of at least
//     three continuous years (or one renewed or extended beyond three years) is excluded from
//     gains as long as it does not exceed 31% of the emoluments earned over the contract.
//   - "gratuity_pension": s.5(4)(g). Gratuity paid into a registered pension scheme is excluded
//     up to KES 360,000 for each year of service, but not for an employee who is eligible for the
//     s.22A pension deduction (one who contributes to a registered scheme).
//
// Anything above the excluded amount is taxed like any other earning.
const (
	TaxableGratuity        = "gratuity"
	TaxableGratuityPension = "gratuity_pension"
)

var (
	// gratuityContractRuleFrom is the commencement of Finance Act 2026 s.3 (s.5(4)(ga)).
	gratuityContractRuleFrom = time.Date(2026, 7, 1, 0, 0, 0, 0, time.UTC)
	gratuityContractShare    = decimal.RequireFromString("0.31")
	gratuityPensionPerYear   = decimal.NewFromInt(360000)
)

// gratuityFacts is what the exclusion needs about one employee for the period.
type gratuityFacts struct {
	// ContractStart and ContractEnd are the contract in force for the period (or the one that
	// just ended). A nil start means no contract: s.5(4)(ga) cannot apply.
	ContractStart, ContractEnd *time.Time
	// Emoluments is the pay earned over the contract up to and including this period, gratuity
	// itself excluded.
	Emoluments decimal.Decimal
	// AlreadyExcluded is the gratuity already left out of tax for the same contract (or, for the
	// pension rule, the same service) in earlier periods.
	AlreadyExcluded decimal.Decimal
	// ServiceStart is when the employee's service began (date joined, else the earliest contract).
	ServiceStart *time.Time
	// PensionMember is true when the employee contributes to a registered pension scheme, which
	// makes them eligible for the s.22A deduction and so outside s.5(4)(g).
	PensionMember bool
}

// gratuityExcluded returns the part of a gratuity amount paid in period that is excluded from tax.
func gratuityExcluded(status string, amount decimal.Decimal, period time.Time, f gratuityFacts) decimal.Decimal {
	if !amount.IsPositive() {
		return decimal.Zero
	}
	var limit decimal.Decimal
	switch status {
	case TaxableGratuity:
		if period.Before(gratuityContractRuleFrom) || f.ContractStart == nil {
			return decimal.Zero
		}
		end := period.AddDate(0, 1, -1)
		if f.ContractEnd != nil {
			end = *f.ContractEnd
		}
		// Three continuous years: a contract from 1 August 2023 to 31 July 2026 qualifies.
		if f.ContractStart.AddDate(3, 0, 0).After(end.AddDate(0, 0, 1)) {
			return decimal.Zero // shorter than three continuous years
		}
		limit = f.Emoluments.Mul(gratuityContractShare)
	case TaxableGratuityPension:
		if f.PensionMember || f.ServiceStart == nil {
			return decimal.Zero
		}
		limit = gratuityPensionPerYear.Mul(decimal.NewFromInt(int64(completedYears(*f.ServiceStart, period.AddDate(0, 1, -1)))))
	default:
		return decimal.Zero
	}
	room := limit.Sub(f.AlreadyExcluded)
	if !room.IsPositive() {
		return decimal.Zero
	}
	return decimal.Min(amount, room).Round(2)
}

// completedYears counts whole years from start to end.
func completedYears(start, end time.Time) int {
	n := 0
	for !start.AddDate(n+1, 0, 0).After(end) {
		n++
	}
	return n
}
