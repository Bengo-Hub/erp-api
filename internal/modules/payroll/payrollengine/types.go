// Package payrollengine is the ERP-OWNED, pure, deterministic payroll tax engine
// (port of hrm/payroll/services/core_calculations.py + dynamic_deduction_engine.py).
//
// Design rules (sprint-2 spec / gaps-and-bugs §2):
//   - decimal throughout (shopspring/decimal); NEVER float (§2.1).
//   - fail loud: an unresolved/missing formula returns a typed error and aborts the run;
//     there is NO `except -> return 0` silent miscalc (§2.2).
//   - tier detection is data-driven from the rate set, not a hardcoded 8000 literal (§2.4).
//   - SHIF/NHIF cutover is config-driven (which formula is effective), not a hardcoded date.
//   - pure functions only: no persistence here (loan.save() is a separate atomic step, §2.7).
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
	Loans             []Recoverable
	Advances          []Recoverable
	LossDamages       []Recoverable
	NonCashBenefits   decimal.Decimal // sum of effective non-cash benefit amounts
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
	Income      *FormulaRates // PAYE bands + personal relief (required)
	NSSF        *FormulaRates // tiered NSSF (required)
	SHIF        *FormulaRates // SHIF (set when SHIF is effective)
	NHIF        *FormulaRates // legacy NHIF (set when NHIF is effective)
	HousingLevy *FormulaRates // housing levy (required)
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
	CompLoans       = "loans"
	CompAdvances    = "advances"
	CompLossDamages = "loss_damages"
	CompNonCash     = "non_cash_benefits"
)

// DefaultDeductionOrder mirrors dynamic_deduction_engine._get_default_deduction_order.
func DefaultDeductionOrder() []Phase {
	return []Phase{
		{Name: PhaseBeforeTax, Components: []string{CompNSSF, CompSHIF, CompHousingLevy}},
		{Name: PhaseAfterTax, Components: []string{CompPAYE}},
		{Name: PhaseAfterPAYE, Components: []string{CompLoans, CompAdvances, CompLossDamages}},
		{Name: PhaseFinal, Components: []string{CompNonCash}},
	}
}

// Inf is the open upper bound sentinel for a Band.
var Inf = decimal.NewFromInt(1).Shift(30) // 1e30, effectively unbounded for payroll
