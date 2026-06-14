package payrollengine

import (
	"fmt"
	"sort"

	"github.com/shopspring/decimal"
)

// two is the rounding scale for persisted statutory amounts (cents).
const moneyScale = 2

// CalculateIncomeTax computes progressive PAYE on taxablePay using the income bands.
// Port of core_calculations.calculate_income_tax — but fails loud when bands are missing
// instead of returning 0 (gaps §2.2). Returns gross PAYE before personal relief.
func CalculateIncomeTax(rates *FormulaRates, taxablePay decimal.Decimal) (decimal.Decimal, error) {
	if rates == nil || len(rates.Bands) == 0 {
		return decimal.Zero, fmt.Errorf("%w: income/PAYE bands", ErrFormulaNotConfigured)
	}
	if taxablePay.LessThanOrEqual(decimal.Zero) {
		return decimal.Zero, nil
	}
	bands := sortedBands(rates.Bands)
	total := decimal.Zero
	for _, b := range bands {
		if taxablePay.LessThanOrEqual(b.From) {
			continue
		}
		span := b.To.Sub(b.From)
		over := taxablePay.Sub(b.From)
		taxable := decimalMin(span, decimalMax(decimal.Zero, over))
		total = total.Add(taxable.Mul(b.Rate))
		if taxablePay.LessThanOrEqual(b.To) {
			break
		}
	}
	return total, nil
}

// NSSFResult is the tiered NSSF breakdown.
type NSSFResult struct {
	Tier1Employee decimal.Decimal
	Tier2Employee decimal.Decimal
	Tier1Employer decimal.Decimal
	Tier2Employer decimal.Decimal
	TotalEmployee decimal.Decimal
	TotalEmployer decimal.Decimal
}

// CalculateNSSF computes tiered NSSF. Tier detection is data-driven: the FIRST band
// (lowest From) is Tier 1, the SECOND distinct band is Tier 2 — NOT a hardcoded 8000
// literal (gaps §2.4). Fails loud when no bands are configured.
func CalculateNSSF(rates *FormulaRates, salary decimal.Decimal) (NSSFResult, error) {
	if rates == nil || len(rates.Bands) == 0 {
		return NSSFResult{}, fmt.Errorf("%w: NSSF tiers", ErrFormulaNotConfigured)
	}
	bands := sortedBands(rates.Bands)
	empPct := percentageOrDefault(rates.EmployeePercentage, decimal.NewFromInt(1))
	erPct := rates.EmployerPercentage

	var res NSSFResult
	seen := map[string]bool{}
	tierIdx := 0
	for _, b := range bands {
		key := b.From.String() + ":" + b.To.String()
		if seen[key] {
			continue
		}
		seen[key] = true
		if salary.LessThanOrEqual(b.From) {
			tierIdx++
			continue
		}
		span := b.To.Sub(b.From)
		over := salary.Sub(b.From)
		base := decimalMin(span, decimalMax(decimal.Zero, over))
		contribution := base.Mul(b.Rate)
		emp := contribution.Mul(empPct)
		er := contribution.Mul(erPct)
		if tierIdx == 0 {
			res.Tier1Employee = res.Tier1Employee.Add(emp)
			res.Tier1Employer = res.Tier1Employer.Add(er)
		} else {
			res.Tier2Employee = res.Tier2Employee.Add(emp)
			res.Tier2Employer = res.Tier2Employer.Add(er)
		}
		tierIdx++
	}
	res.Tier1Employee = round0(res.Tier1Employee)
	res.Tier2Employee = round0(res.Tier2Employee)
	res.Tier1Employer = round0(res.Tier1Employer)
	res.Tier2Employer = round0(res.Tier2Employer)
	res.TotalEmployee = res.Tier1Employee.Add(res.Tier2Employee)
	res.TotalEmployer = res.Tier1Employer.Add(res.Tier2Employer)
	return res, nil
}

// ContributionResult is the employee/employer contribution for SHIF/NHIF/housing.
type ContributionResult struct {
	Employee decimal.Decimal
	Employer decimal.Decimal
	Relief   decimal.Decimal
}

// CalculateSHIF computes SHIF (% of gross, with a configured minimum encoded as a band
// floor). Port of calculate_shif_contribution; relief repealed (Dec 2024) => 0.
func CalculateSHIF(rates *FormulaRates, salary decimal.Decimal) (ContributionResult, error) {
	if rates == nil || len(rates.Bands) == 0 {
		return ContributionResult{}, fmt.Errorf("%w: SHIF", ErrFormulaNotConfigured)
	}
	return percentContribution(rates, salary), nil
}

// CalculateHousingLevy computes the housing levy (% of gross). Relief repealed => 0.
func CalculateHousingLevy(rates *FormulaRates, salary decimal.Decimal) (ContributionResult, error) {
	if rates == nil || len(rates.Bands) == 0 {
		return ContributionResult{}, fmt.Errorf("%w: housing levy", ErrFormulaNotConfigured)
	}
	return percentContribution(rates, salary), nil
}

// CalculateNHIF computes legacy NHIF from a configured banded fixed-amount table.
// There is NO silent hardcoded-2017 fallback (gaps §2.2): missing config => error.
func CalculateNHIF(rates *FormulaRates, salary decimal.Decimal) (ContributionResult, error) {
	if rates == nil || len(rates.Bands) == 0 {
		return ContributionResult{}, fmt.Errorf("%w: NHIF table", ErrFormulaNotConfigured)
	}
	empPct := percentageOrDefault(rates.EmployeePercentage, decimal.NewFromInt(1))
	erPct := rates.EmployerPercentage
	var res ContributionResult
	for _, b := range sortedBands(rates.Bands) {
		if salary.GreaterThanOrEqual(b.From) && salary.LessThanOrEqual(b.To) {
			contribution := b.Amount
			if contribution.LessThan(decimal.NewFromInt(1)) {
				// fractional => treat as a rate of salary (parity with legacy "< 1" branch)
				contribution = salary.Mul(b.Rate)
			}
			res.Employee = round2(contribution.Mul(empPct))
			res.Employer = round2(contribution.Mul(erPct))
			if rates.ApplicableRelief.GreaterThan(decimal.Zero) {
				res.Relief = round2(rates.ApplicableRelief.Mul(res.Employee))
			}
			break
		}
	}
	return res, nil
}

// percentContribution applies banded percentage rates and returns the employee/employer
// split (relief 0 — SHIF/Housing reliefs are repealed).
func percentContribution(rates *FormulaRates, salary decimal.Decimal) ContributionResult {
	empPct := percentageOrDefault(rates.EmployeePercentage, decimal.NewFromInt(1))
	erPct := rates.EmployerPercentage
	var res ContributionResult
	for _, b := range sortedBands(rates.Bands) {
		if salary.GreaterThan(b.From) {
			span := b.To.Sub(b.From)
			over := salary.Sub(b.From)
			base := decimalMin(span, decimalMax(decimal.Zero, over))
			contribution := base.Mul(b.Rate)
			res.Employee = round2(contribution.Mul(empPct))
			res.Employer = round2(contribution.Mul(erPct))
			break
		}
	}
	return res
}

func sortedBands(in []Band) []Band {
	out := make([]Band, len(in))
	copy(out, in)
	sort.SliceStable(out, func(i, j int) bool { return out[i].From.LessThan(out[j].From) })
	return out
}

func percentageOrDefault(v, def decimal.Decimal) decimal.Decimal {
	if v.IsZero() {
		return def
	}
	return v
}

func decimalMin(a, b decimal.Decimal) decimal.Decimal {
	if a.LessThan(b) {
		return a
	}
	return b
}

func decimalMax(a, b decimal.Decimal) decimal.Decimal {
	if a.GreaterThan(b) {
		return a
	}
	return b
}

func round0(v decimal.Decimal) decimal.Decimal { return v.Round(0) }
func round2(v decimal.Decimal) decimal.Decimal { return v.Round(moneyScale) }
