// Package payrollengine is the ERP-OWNED, pure, deterministic payroll tax engine
//
// Design rules:
//   - decimal throughout (shopspring/decimal); NEVER float.
//   - fail loud: an unresolved or missing formula returns a typed error and aborts the run;
//     there is no silent zero.
//   - tier detection is data-driven from the rate set, not a hardcoded 8000 literal.
//   - SHIF/NHIF cutover is config-driven (which formula is effective), not a hardcoded date.
//   - pure functions only: no persistence here (persistence is a separate atomic step).
package payrollengine

import (
	"errors"

	"github.com/shopspring/decimal"
)

// ErrFormulaNotConfigured is returned when a required statutory formula/rate set is
// missing for the period. The caller MUST abort the run (no zeroed statutory line).
var ErrFormulaNotConfigured = errors.New("payrollengine: required formula not configured for period")

// Band is one bracket of a formula: [From, To) charged at Rate (a fraction, e.g. 0.30),
// OR a flat Amount when Amount > 0 (NHIF-style fixed contribution).
type Band struct {
	From   decimal.Decimal
	To     decimal.Decimal // use Inf for an open upper bound
	Rate   decimal.Decimal // fraction (0.30 == 30%)
	Amount decimal.Decimal // flat amount; when > 0 it wins over Rate
}

// FormulaRates is a resolved, period-effective rate set for one statutory item.
type FormulaRates struct {
	Bands              []Band
	EmployeePercentage decimal.Decimal // fraction (1 == 100%)
	EmployerPercentage decimal.Decimal // fraction
	ApplicableRelief   decimal.Decimal // fraction of the contribution that is relieved
	PersonalRelief     decimal.Decimal // absolute amount (income formula only)
}

// EmployeeInput is the per-employee data the engine needs for one period. All amounts
// are decimal. Recoverables are passed in already filtered/effective-dated by the caller.
type EmployeeInput struct {
	GrossPay    decimal.Decimal
	TaxCategory string // "primary" | "secondary" | "none"
	// TaxableAllowances is additional TAXABLE cash income for the period — taxable cash allowances
	// plus the taxable EXCESS of per-diem/mileage over their KRA caps. It is added to gross for
	// PAYE/statutory and to net pay (the employee receives this cash). NON-taxable reimbursements
	// must NOT be put here — they are paid via AP (treasury), never through payroll gross, so they
	// don't inflate PAYE. Additive: zero by default (no change to existing callers).
	TaxableAllowances decimal.Decimal
	// UnpaidTime is pay withheld for approved attendance deductions (lateness, unexcused absence).
	// It is loss of pay, not a recovery: it comes off gross BEFORE statutory deductions and PAYE,
	// so the employee is not taxed on pay they did not earn. Capped at gross. Zero by default.
	UnpaidTime  decimal.Decimal
	Loans       []Recoverable
	Advances    []Recoverable
	LossDamages []Recoverable
	// StaffPurchases are POS-origin staff credit/layaway balances funded from salary — recovered
	// in the after-PAYE phase like loans/advances. Filtered/effective-dated by the caller.
	StaffPurchases  []Recoverable
	NonCashBenefits decimal.Decimal // sum of effective non-cash benefit amounts

	// --- KRA reliefs (per-employee actual amounts; all additive, zero by default) ---
	// InsurancePremium is the monthly life/health/education premium the employee pays. It yields
	// an insurance-relief CREDIT (min(rate*premium, cap)) that reduces PAYE like personal relief.
	InsurancePremium decimal.Decimal
	// PensionContribution is the monthly contribution to a registered pension/provident scheme
	// (beyond NSSF). Deductible PRE-TAX up to min(30% of gross, actual, statutory cap).
	PensionContribution decimal.Decimal
	// MortgageInterest is monthly owner-occupier mortgage interest — an allowable PRE-TAX
	// deduction up to the statutory monthly cap.
	MortgageInterest decimal.Decimal
	// DisabilityExempt marks an employee holding a PWD tax-exemption certificate: the first
	// DisabilityExemptAmount of chargeable pay is exempt from PAYE.
	DisabilityExempt bool
}

// Recoverable is an installment-based deduction (loan/advance/loss-damage). The engine
// recovers min(Installment, Outstanding) and never persists.
type Recoverable struct {
	Installment decimal.Decimal
	Outstanding decimal.Decimal
}

// Config bundles the resolved rate sets + deduction ordering for a run. The service
// builds this from tenant-scoped, effective-dated Ent rows; a nil pointer for a required
// statutory item makes the engine fail loud.
type Config struct {
	Income *FormulaRates // PAYE bands + personal relief (required)
	// IncomeSecondary is the PAYE table for secondary employees (a second employer): income is
	// taxed at the top marginal rate (a flat band, no personal relief) because the primary
	// employer already consumed the lower bands + relief. Optional — when nil, secondary
	// employees fall back to the primary bands with relief suppressed (legacy behaviour).
	IncomeSecondary *FormulaRates
	NSSF            *FormulaRates // tiered NSSF (required)
	SHIF            *FormulaRates // SHIF (set when SHIF is effective)
	NHIF            *FormulaRates // legacy NHIF (set when NHIF is effective)
	HousingLevy     *FormulaRates // housing levy (required)
	// NITA is the industrial training levy (employer-only, flat per employee per month —
	// KES 50). Optional: nil when the tenant has no NITA formula configured. Never affects
	// employee deductions or net pay; surfaces as an employer contribution only.
	NITA *FormulaRates
	// Disabled marks components (Comp* codes) a tenant has DELIBERATELY switched off via
	// statutory settings — the engine skips them silently. This is distinct from a missing
	// formula on an ENABLED component, which still fails loud (ErrFormulaNotConfigured,
	//). A nil map means everything is enabled (zero-value Config unchanged).
	Disabled map[string]bool
	// DeductionOrder drives phasing. Empty => DefaultDeductionOrder().
	DeductionOrder []Phase
	// RecoverAdvances gates salary-advance recovery for this run.
	RecoverAdvances bool
	// NonCashAsTaxable corrects non-cash benefit handling: when true the taxable EXCESS of
	// non-cash benefits over NonCashMonthlyExemption is ADDED to taxable pay (so PAYE is charged
	// on the benefit) and the benefit is NOT deducted from cash net pay (it is in-kind). Default
	// false preserves the legacy behaviour (non-cash deducted from net, untaxed) until a tenant
	// opts in, so existing payslips are unchanged.
	NonCashAsTaxable bool
	// NonCashMonthlyExemption is the de-minimis monthly non-cash benefit exemption (KRA: aggregate
	// non-cash benefits up to KES 36,000/yr ≈ KES 3,000/month are not taxable). Only the excess is
	// taxed. Applied only when NonCashAsTaxable is true.
	NonCashMonthlyExemption decimal.Decimal

	// --- KRA relief caps (resolved from the tenant's active PayrollRelief rows). A zero cap means
	// the relief is NOT configured and is skipped entirely, so a zero-value Config is unchanged. ---
	InsuranceReliefRate    decimal.Decimal // fraction of premium relieved (0.15 == 15%)
	InsuranceReliefCap     decimal.Decimal // monthly ceiling on the insurance-relief credit (5,000)
	PensionReliefCap       decimal.Decimal // monthly ceiling on deductible pension (30,000)
	MortgageReliefCap      decimal.Decimal // monthly ceiling on deductible mortgage interest (30,000)
	DisabilityExemptAmount decimal.Decimal // monthly chargeable-pay exemption for PWD holders (150,000)
}

// Phase is one deduction phase with the components applied in it.
type Phase struct {
	Name       string   `json:"phase"`
	Components []string `json:"components"`
}

// Phase names + component identifiers (parity with the legacy engine).
const (
	PhaseBeforeTax = "before_tax"
	PhaseAfterTax  = "after_tax"
	PhaseAfterPAYE = "after_paye"
	PhaseFinal     = "final"

	CompNSSF        = "nssf"
	CompSHIF        = "shif"
	CompNHIF        = "nhif"
	CompHousingLevy = "housing_levy"
	CompPAYE        = "paye"
	// CompNITA is computed outside the phase loop (employer-only); the constant exists for
	// Config.Disabled keying and payslip-line coding, not for DeductionOrder membership.
	CompNITA          = "nita"
	CompLoans         = "loans"
	CompAdvances      = "advances"
	CompLossDamages   = "loss_damages"
	CompStaffPurchase = "staff_purchase"
	CompNonCash       = "non_cash_benefits"
)

// DefaultDeductionOrder mirrors dynamic_deduction_engine._get_default_deduction_order.
func DefaultDeductionOrder() []Phase {
	return []Phase{
		{Name: PhaseBeforeTax, Components: []string{CompNSSF, CompSHIF, CompHousingLevy}},
		{Name: PhaseAfterTax, Components: []string{CompPAYE}},
		{Name: PhaseAfterPAYE, Components: []string{CompLoans, CompAdvances, CompLossDamages, CompStaffPurchase}},
		{Name: PhaseFinal, Components: []string{CompNonCash}},
	}
}

// Inf is the open upper bound sentinel for a Band.
var Inf = decimal.NewFromInt(1).Shift(30) // 1e30, effectively unbounded for payroll
