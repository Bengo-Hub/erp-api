package payrollengine

import (
	"fmt"

	"github.com/shopspring/decimal"
)

// PayslipResult is the engine's deterministic output for one employee/period. All fields
// are decimal; the service maps these straight onto the Payslip Ent row.
type PayslipResult struct {
	GrossPay          decimal.Decimal
	TaxablePay        decimal.Decimal
	PAYE              decimal.Decimal // after personal relief, floored at 0
	PersonalRelief    decimal.Decimal
	GrossPayAfterTax  decimal.Decimal
	SHIFOrNHIF        decimal.Decimal
	HousingLevy       decimal.Decimal
	NSSFEmployeeTier1 decimal.Decimal
	NSSFEmployeeTier2 decimal.Decimal
	NSSFEmployer      decimal.Decimal

	DeductionsBeforeTax decimal.Decimal
	DeductionsAfterTax  decimal.Decimal
	DeductionsAfterPAYE decimal.Decimal
	DeductionsFinal     decimal.Decimal

	NetPay decimal.Decimal
}

// Compute runs the phased deduction engine for one employee. It fails loud if a required
// statutory formula is missing (gaps §2.2) — the caller aborts the whole run.
//
// Phasing (port of dynamic_deduction_engine.calculate_deductions_in_order):
//
//	before_tax (NSSF/SHIF|NHIF/Housing) -> taxable = gross - before_tax
//	after_tax  (PAYE on taxable, less personal relief)
//	after_paye (loans/advances/loss-damages, capped at outstanding)
//	final      (non-cash benefits)
func Compute(cfg Config, in EmployeeInput) (PayslipResult, error) {
	if cfg.Income == nil {
		return PayslipResult{}, fmt.Errorf("%w: income/PAYE", ErrFormulaNotConfigured)
	}
	order := cfg.DeductionOrder
	if len(order) == 0 {
		order = DefaultDeductionOrder()
	}

	// Effective cash gross = base salary + taxable cash allowances (per-diem/mileage excess, taxable
	// allowances). Non-taxable reimbursements are NEVER here (they go via AP). Statutory + PAYE +
	// net pay all use this gross. Additive: TaxableAllowances defaults to zero.
	gross := in.GrossPay.Add(in.TaxableAllowances)
	res := PayslipResult{GrossPay: gross}
	var nssf NSSFResult

	for _, phase := range order {
		for _, comp := range phase.Components {
			switch comp {
			case CompNSSF:
				n, err := CalculateNSSF(cfg.NSSF, gross)
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
				c, err := CalculateSHIF(cfg.SHIF, gross)
				if err != nil {
					return PayslipResult{}, err
				}
				res.SHIFOrNHIF = c.Employee
				addPhase(&res, phase.Name, c.Employee)

			case CompNHIF:
				if cfg.NHIF == nil {
					continue
				}
				c, err := CalculateNHIF(cfg.NHIF, gross)
				if err != nil {
					return PayslipResult{}, err
				}
				res.SHIFOrNHIF = c.Employee
				addPhase(&res, phase.Name, c.Employee)

			case CompHousingLevy:
				c, err := CalculateHousingLevy(cfg.HousingLevy, gross)
				if err != nil {
					return PayslipResult{}, err
				}
				res.HousingLevy = c.Employee
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

	_ = nssf
	totalDeductions := res.DeductionsBeforeTax.
		Add(res.DeductionsAfterTax).
		Add(res.DeductionsAfterPAYE).
		Add(res.DeductionsFinal)
	res.NetPay = round2(gross.Sub(totalDeductions))
	return res, nil
}

// taxableNonCash returns the taxable portion of non-cash benefits for the period: the excess over
// the monthly de-minimis exemption, only when NonCashAsTaxable is enabled. Otherwise zero.
func taxableNonCash(cfg Config, in EmployeeInput) decimal.Decimal {
	if !cfg.NonCashAsTaxable {
		return decimal.Zero
	}
	excess := in.NonCashBenefits.Sub(cfg.NonCashMonthlyExemption)
	if excess.LessThan(decimal.Zero) {
		return decimal.Zero
	}
	return excess
}

// applyPAYE computes taxable pay (gross - before-tax deductions), progressive PAYE, then
// subtracts personal relief, flooring at zero. "secondary" category taxes the whole
// taxable amount at the bands with no relief; "none" => no PAYE.
func applyPAYE(res *PayslipResult, cfg Config, in EmployeeInput) error {
	// res.GrossPay already includes taxable allowances. Taxable pay = gross − before-tax deductions
	// + the taxable excess of non-cash benefits (when NonCashAsTaxable is enabled).
	taxable := res.GrossPay.Sub(res.DeductionsBeforeTax).Add(taxableNonCash(cfg, in))
	if taxable.LessThan(decimal.Zero) {
		taxable = decimal.Zero
	}
	res.TaxablePay = taxable

	// "none" => no PAYE; "" defaults to primary (legacy default behaviour).
	if in.TaxCategory == "none" {
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
	relief := decimal.Zero
	if in.TaxCategory != "secondary" {
		relief = cfg.Income.PersonalRelief
	}
	paye := gross.Sub(relief)
	if paye.LessThan(decimal.Zero) {
		paye = decimal.Zero
	}
	res.PAYE = round2(paye)
	res.PersonalRelief = relief
	res.GrossPayAfterTax = round2(taxable.Sub(res.PAYE))
	addPhase(res, PhaseAfterTax, res.PAYE)
	return nil
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
