package payrollengine

import (
	"fmt"
	"sort"

	"github.com/shopspring/decimal"
)

// PayslipResult is the engine's deterministic output for one employee/period. All fields
// are decimal; the service maps these straight onto the Payslip Ent row.
type PayslipResult struct {
	GrossPay decimal.Decimal
	// UnpaidTime is the attendance deduction actually taken off gross (EmployeeInput.UnpaidTime,
	// capped at gross). GrossPay is already net of it.
	UnpaidTime     decimal.Decimal
	TaxablePay     decimal.Decimal
	PAYE           decimal.Decimal // after all reliefs, floored at 0
	PersonalRelief decimal.Decimal
	// InsuranceRelief is the applied insurance-relief credit (min(rate*premium, cap)); it reduces
	// PAYE alongside PersonalRelief. PensionDeduction/MortgageDeduction are the applied PRE-TAX
	// allowable deductions, and DisabilityExemption the applied chargeable-pay exemption — all
	// surfaced for the P9/P9A card. Zero unless the employee has the corresponding relief input.
	InsuranceRelief     decimal.Decimal
	PensionDeduction    decimal.Decimal
	MortgageDeduction   decimal.Decimal
	// PostRetirementMedicalDeduction is the applied pre-tax post-retirement medical deduction.
	PostRetirementMedicalDeduction decimal.Decimal
	DisabilityExemption decimal.Decimal
	GrossPayAfterTax    decimal.Decimal
	SHIFOrNHIF          decimal.Decimal
	HousingLevy         decimal.Decimal
	NSSFEmployeeTier1   decimal.Decimal
	NSSFEmployeeTier2   decimal.Decimal
	NSSFEmployer        decimal.Decimal
	HousingLevyEmployer decimal.Decimal // employer match; never part of deductions or net pay
	// NITAEmployer is the employer-only industrial training levy (flat per employee/month).
	// It never enters deductions or net pay.
	NITAEmployer decimal.Decimal
	// FBTEmployer is the employer's fringe benefit tax on the employee's low-interest staff loans.
	FBTEmployer decimal.Decimal
	// Reimbursements is the non-taxable expense claim repayment added to net pay (never to gross).
	Reimbursements decimal.Decimal
	// NonTaxableEarnings is the non-taxable component pay included in GrossPay.
	NonTaxableEarnings decimal.Decimal
	// OtherDeductions is the total of the opt-in component deductions taken, and
	// OtherDeductionsApplied the amount taken for each EmployeeInput.OtherDeductions entry (same
	// order). DeductionShortfall is what could not be taken because net pay ran out: an opt-in
	// deduction never takes net pay below zero, the remainder is reported here, not carried.
	OtherDeductions        decimal.Decimal
	OtherDeductionsApplied []decimal.Decimal
	DeductionShortfall     decimal.Decimal

	DeductionsBeforeTax decimal.Decimal
	DeductionsAfterTax  decimal.Decimal
	DeductionsAfterPAYE decimal.Decimal
	DeductionsFinal     decimal.Decimal

	NetPay decimal.Decimal
}

// Compute runs the phased deduction engine for one employee. It fails loud if a required
// statutory formula is missing — the caller aborts the whole run.
//
// Phasing (port of dynamic_deduction_engine.calculate_deductions_in_order):
//
//	before_tax (NSSF/SHIF|NHIF/Housing) -> taxable = gross - before_tax
//	after_tax  (PAYE on taxable, less personal relief)
//	after_paye (loans/advances/loss-damages, capped at outstanding)
//	final      (non-cash benefits)
func Compute(cfg Config, in EmployeeInput) (PayslipResult, error) {
	if cfg.Income == nil && !cfg.Disabled[CompPAYE] {
		return PayslipResult{}, fmt.Errorf("%w: income/PAYE", ErrFormulaNotConfigured)
	}
	order := cfg.DeductionOrder
	if len(order) == 0 {
		order = DefaultDeductionOrder()
	}

	// Effective cash gross = base salary + taxable cash allowances (per-diem/mileage excess, taxable
	// allowances). Non-taxable reimbursements are NEVER here (they are added to net pay at the end). Statutory + PAYE +
	// net pay all use this gross. Additive: TaxableAllowances defaults to zero.
	gross := in.GrossPay.Add(in.TaxableAllowances)
	// Approved attendance deductions are unearned pay: they reduce gross before anything is
	// charged on it, and never below zero.
	unpaid := decimal.Zero
	if in.UnpaidTime.IsPositive() {
		unpaid = decimal.Min(in.UnpaidTime, gross)
		gross = gross.Sub(unpaid)
	}
	res := PayslipResult{GrossPay: gross, UnpaidTime: unpaid}
	var nssf NSSFResult

	for _, phase := range order {
		for _, comp := range phase.Components {
			// Deliberate tenant opt-out: skip silently. PAYE is the exception — applyPAYE must
			// still run to set TaxablePay/GrossPayAfterTax (it charges no tax when disabled).
			if cfg.Disabled[comp] && comp != CompPAYE {
				continue
			}
			switch comp {
			case CompNSSF:
				n, err := CalculateNSSF(cfg.NSSF, levyBase(gross, in.LevyAdjust.NSSF))
				if err != nil {
					return PayslipResult{}, err
				}
				nssf = n
				res.NSSFEmployeeTier1 = n.Tier1Employee
				res.NSSFEmployeeTier2 = n.Tier2Employee
				res.NSSFEmployer = n.TotalEmployer
				addPhase(&res, phase.Name, n.TotalEmployee)

			case CompSHIF:
				if cfg.SHIF == nil {
					// SHIF not effective this period; skip (NHIF handles health then).
					continue
				}
				c, err := CalculateSHIF(cfg.SHIF, levyBase(gross, in.LevyAdjust.SHIF))
				if err != nil {
					return PayslipResult{}, err
				}
				res.SHIFOrNHIF = c.Employee
				addPhase(&res, phase.Name, c.Employee)

			case CompNHIF:
				if cfg.NHIF == nil {
					continue
				}
				c, err := CalculateNHIF(cfg.NHIF, levyBase(gross, in.LevyAdjust.SHIF))
				if err != nil {
					return PayslipResult{}, err
				}
				res.SHIFOrNHIF = c.Employee
				addPhase(&res, phase.Name, c.Employee)

			case CompHousingLevy:
				c, err := CalculateHousingLevy(cfg.HousingLevy, levyBase(gross, in.LevyAdjust.HousingLevy))
				if err != nil {
					return PayslipResult{}, err
				}
				res.HousingLevy = c.Employee
				res.HousingLevyEmployer = c.Employer
				addPhase(&res, phase.Name, c.Employee)

			case CompPAYE:
				if err := applyPAYE(&res, cfg, in); err != nil {
					return PayslipResult{}, err
				}

			case CompLoans:
				addPhase(&res, phase.Name, sumRecoverables(in.Loans))
			case CompAdvances:
				if cfg.RecoverAdvances {
					addPhase(&res, phase.Name, sumRecoverables(in.Advances))
				}
			case CompLossDamages:
				addPhase(&res, phase.Name, sumRecoverables(in.LossDamages))
			case CompStaffPurchase:
				// POS-origin staff purchases (goods taken on credit/layaway, funded from salary),
				// recovered like any other installment recoverable.
				addPhase(&res, phase.Name, sumRecoverables(in.StaffPurchases))
			case CompNonCash:
				// When NonCashAsTaxable, the benefit is in-kind: it is taxed via the taxable
				// add-back in applyPAYE and must NOT be deducted from cash net pay. Legacy mode
				// (default) keeps deducting it from net pay, untaxed.
				if !cfg.NonCashAsTaxable {
					addPhase(&res, phase.Name, in.NonCashBenefits)
				}

			default:
				return PayslipResult{}, fmt.Errorf("payrollengine: unknown deduction component %q", comp)
			}
		}
	}

	// NITA (employer-only levy) is computed OUTSIDE the phase loop: stored per-tenant
	// deduction orders predate it, and it never touches employee deductions or net pay.
	if cfg.NITA != nil && !cfg.Disabled[CompNITA] {
		nita, err := CalculateNITA(cfg.NITA)
		if err != nil {
			return PayslipResult{}, err
		}
		res.NITAEmployer = nita
	}
	res.FBTEmployer = fringeBenefitTax(cfg.FBT, in.StaffLoans)

	_ = nssf
	// Non-taxable component earnings are pay, so they are part of gross and net pay, but they were
	// kept out of the statutory bases and PAYE above.
	if in.NonTaxableEarnings.IsPositive() {
		res.NonTaxableEarnings = round2(in.NonTaxableEarnings)
		gross = gross.Add(res.NonTaxableEarnings)
		res.GrossPay = gross
	}
	applyOtherDeductions(&res, order, gross, in.OtherDeductions)

	totalDeductions := res.DeductionsBeforeTax.
		Add(res.DeductionsAfterTax).
		Add(res.DeductionsAfterPAYE).
		Add(res.DeductionsFinal)
	// Non-taxable reimbursements are repaid with the salary: they add to net pay only.
	if in.Reimbursements.IsPositive() {
		res.Reimbursements = round2(in.Reimbursements)
	}
	res.NetPay = round2(gross.Sub(totalDeductions).Add(res.Reimbursements))
	return res, nil
}

// applyOtherDeductions takes the opt-in component deductions after everything else (statutory,
// PAYE, loans, advances and the other recoverables), in deduction-order phase then priority
// order. Each is capped at the cash net pay still left, so these deductions never push net pay
// below zero; whatever could not be taken is reported in DeductionShortfall and is not carried
// to the next period. Loans and advances are untouched by this rule.
func applyOtherDeductions(res *PayslipResult, order []Phase, gross decimal.Decimal, ds []Deduction) {
	if len(ds) == 0 {
		return
	}
	phaseRank := map[string]int{}
	for i, p := range order {
		phaseRank[p.Name] = i
	}
	rank := func(phase string) int {
		if r, ok := phaseRank[phase]; ok {
			return r
		}
		return len(order) // unknown phase: after the known ones
	}
	idx := make([]int, len(ds))
	for i := range idx {
		idx[i] = i
	}
	sort.SliceStable(idx, func(a, b int) bool {
		da, db := ds[idx[a]], ds[idx[b]]
		if ra, rb := rank(da.Phase), rank(db.Phase); ra != rb {
			return ra < rb
		}
		return da.Priority < db.Priority
	})

	left := gross.Sub(res.DeductionsBeforeTax).Sub(res.DeductionsAfterTax).
		Sub(res.DeductionsAfterPAYE).Sub(res.DeductionsFinal)
	res.OtherDeductionsApplied = make([]decimal.Decimal, len(ds))
	for _, i := range idx {
		want := round2(ds[i].Amount)
		if !want.IsPositive() {
			res.OtherDeductionsApplied[i] = decimal.Zero
			continue
		}
		take := want
		if left.LessThan(take) {
			take = decimal.Max(left, decimal.Zero)
		}
		take = round2(take)
		res.OtherDeductionsApplied[i] = take
		res.DeductionShortfall = res.DeductionShortfall.Add(want.Sub(take))
		res.OtherDeductions = res.OtherDeductions.Add(take)
		left = left.Sub(take)
		// The before-tax and after-tax totals stay statutory only: those fed taxable pay.
		phase := PhaseAfterPAYE
		if ds[i].Phase == PhaseFinal {
			phase = PhaseFinal
		}
		addPhase(res, phase, take)
	}
}

// levyBase is gross moved by a levy's adjustment, never below zero.
func levyBase(gross, adjust decimal.Decimal) decimal.Decimal {
	return decimal.Max(decimal.Zero, gross.Add(adjust))
}

// fringeBenefitTax is the employer's monthly fringe benefit tax (s.12B): the rate times, for each
// loan, the month's interest gap between the market rate and the loan's rate (never below zero).
func fringeBenefitTax(r *FBTRates, loans []LoanBenefit) decimal.Decimal {
	if r == nil || !r.TaxRate.IsPositive() {
		return decimal.Zero
	}
	value := decimal.Zero
	perMonth := decimal.NewFromInt(1200) // percent per year to a fraction per month
	for _, l := range loans {
		gap := r.MarketRate.Sub(l.AnnualRate)
		if !gap.IsPositive() || !l.Outstanding.IsPositive() {
			continue
		}
		value = value.Add(l.Outstanding.Mul(gap).Div(perMonth))
	}
	return round2(value.Mul(r.TaxRate))
}

// taxableNonCash returns the taxable value of non-cash benefits for the period, only when
// NonCashAsTaxable is enabled. Employer meals are reduced by their monthly exemption first; the
// aggregate is then taxed in full when it reaches NonCashTaxThreshold and not at all below it.
func taxableNonCash(cfg Config, in EmployeeInput) decimal.Decimal {
	if !cfg.NonCashAsTaxable {
		return decimal.Zero
	}
	meals := decimal.Min(in.MealBenefits, in.NonCashBenefits)
	taxableMeals := decimal.Max(decimal.Zero, meals.Sub(cfg.MealsMonthlyExemption))
	aggregate := in.NonCashBenefits.Sub(meals).Add(taxableMeals)
	if !aggregate.IsPositive() || aggregate.LessThan(cfg.NonCashTaxThreshold) {
		return decimal.Zero
	}
	return aggregate
}

// applyPAYE computes taxable pay (gross - before-tax deductions), progressive PAYE, then
// subtracts personal relief, flooring at zero. "secondary" category taxes the whole
// taxable amount at the bands with no relief; "none" => no PAYE.
func applyPAYE(res *PayslipResult, cfg Config, in EmployeeInput) error {
	// res.GrossPay already includes taxable allowances. Taxable pay = gross − before-tax deductions
	// + the taxable excess of non-cash benefits (when NonCashAsTaxable is enabled).
	taxable := res.GrossPay.Sub(res.DeductionsBeforeTax).Add(taxableNonCash(cfg, in)).Add(in.TaxableOnly).Add(in.LevyAdjust.PAYE)
	if taxable.LessThan(decimal.Zero) {
		taxable = decimal.Zero
	}

	// KRA allowable PRE-TAX reliefs further reduce chargeable pay. These lower PAYE/chargeable pay
	// only — the contributions are remitted separately (private scheme / bank / a deduction line),
	// so they do NOT alter net pay here. Each is gated on its cap being configured, so a zero-value
	// Config (no reliefs resolved) leaves taxable pay exactly as before.
	//
	// Deductible pension (s.22A): min(actual, statutory monthly cap, 30% of pensionable pay).
	if in.PensionContribution.IsPositive() && cfg.PensionReliefCap.IsPositive() {
		pensionable := in.PensionablePay
		if !pensionable.IsPositive() {
			pensionable = res.GrossPay
		}
		pension := minDec(in.PensionContribution, cfg.PensionReliefCap, pensionable.Mul(pct30))
		res.PensionDeduction = round2(pension)
		taxable = taxable.Sub(pension)
	}
	// Owner-occupier mortgage interest: min(actual, statutory monthly cap).
	if in.MortgageInterest.IsPositive() && cfg.MortgageReliefCap.IsPositive() {
		mortgage := minDec(in.MortgageInterest, cfg.MortgageReliefCap)
		res.MortgageDeduction = round2(mortgage)
		taxable = taxable.Sub(mortgage)
	}
	// Post-retirement medical fund contribution: min(actual, statutory monthly cap).
	if in.PostRetirementMedical.IsPositive() && cfg.PostRetirementMedicalCap.IsPositive() {
		prmf := minDec(in.PostRetirementMedical, cfg.PostRetirementMedicalCap)
		res.PostRetirementMedicalDeduction = round2(prmf)
		taxable = taxable.Sub(prmf)
	}
	// PWD exemption certificate: the first DisabilityExemptAmount of chargeable pay is exempt.
	if in.DisabilityExempt && cfg.DisabilityExemptAmount.IsPositive() {
		exempt := minDec(taxable, cfg.DisabilityExemptAmount)
		res.DisabilityExemption = round2(exempt)
		taxable = taxable.Sub(exempt)
	}
	if taxable.LessThan(decimal.Zero) {
		taxable = decimal.Zero
	}
	res.TaxablePay = taxable

	// "none" => no PAYE; "" defaults to primary (legacy default behaviour). A tenant-level
	// PAYE opt-out behaves exactly like "none": taxable pay is still reported, no tax charged.
	if in.TaxCategory == "none" || cfg.Disabled[CompPAYE] {
		res.GrossPayAfterTax = taxable
		return nil
	}

	// Secondary employees use the dedicated secondary table (flat top-rate, no relief) when one is
	// configured; otherwise they fall back to the primary bands with relief suppressed.
	table := cfg.Income
	if in.TaxCategory == "secondary" && cfg.IncomeSecondary != nil {
		table = cfg.IncomeSecondary
	}
	gross, err := CalculateIncomeTax(table, taxable)
	if err != nil {
		return err
	}
	// Relief CREDITS reduce the tax charged. Personal relief plus insurance relief
	// (min(rate*premium, cap)). Secondary employees get no reliefs (consumed by the primary job).
	personal := decimal.Zero
	if in.TaxCategory != "secondary" {
		personal = cfg.Income.PersonalRelief
		if in.InsurancePremium.IsPositive() && cfg.InsuranceReliefRate.IsPositive() && cfg.InsuranceReliefCap.IsPositive() {
			res.InsuranceRelief = round2(minDec(in.InsurancePremium.Mul(cfg.InsuranceReliefRate), cfg.InsuranceReliefCap))
		}
	}
	paye := gross.Sub(personal).Sub(res.InsuranceRelief)
	if paye.LessThan(decimal.Zero) {
		paye = decimal.Zero
	}
	res.PAYE = round2(paye)
	res.PersonalRelief = personal
	res.GrossPayAfterTax = round2(taxable.Sub(res.PAYE))
	addPhase(res, PhaseAfterTax, res.PAYE)
	return nil
}

// pct30 is the 30%-of-gross ceiling used in the deductible-pension test.
var pct30 = decimal.NewFromFloat(0.30)

// minDec returns the smallest of the given decimals (at least one required).
func minDec(first decimal.Decimal, rest ...decimal.Decimal) decimal.Decimal {
	m := first
	for _, v := range rest {
		if v.LessThan(m) {
			m = v
		}
	}
	return m
}

func addPhase(res *PayslipResult, phase string, amt decimal.Decimal) {
	amt = round2(amt)
	switch phase {
	case PhaseBeforeTax:
		res.DeductionsBeforeTax = res.DeductionsBeforeTax.Add(amt)
	case PhaseAfterTax:
		res.DeductionsAfterTax = res.DeductionsAfterTax.Add(amt)
	case PhaseAfterPAYE:
		res.DeductionsAfterPAYE = res.DeductionsAfterPAYE.Add(amt)
	case PhaseFinal:
		res.DeductionsFinal = res.DeductionsFinal.Add(amt)
	}
}

// sumRecoverables returns the total recovered this period: sum of min(installment, outstanding).
func sumRecoverables(items []Recoverable) decimal.Decimal {
	total := decimal.Zero
	for _, r := range items {
		if r.Outstanding.LessThanOrEqual(decimal.Zero) || r.Installment.LessThanOrEqual(decimal.Zero) {
			continue
		}
		total = total.Add(decimalMin(r.Installment, r.Outstanding))
	}
	return total
}
