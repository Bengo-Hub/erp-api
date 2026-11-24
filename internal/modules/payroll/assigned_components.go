package payroll

import (
	"sort"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// DeductionLine is one assigned opt-in deduction carried to the payslip. Index is its position in
// the engine input's OtherDeductions, so the line shows the amount the engine actually took.
type DeductionLine struct {
	ComponentID uuid.UUID
	Code        string
	Label       string
	Phase       string
	Amount      decimal.Decimal // amount due this period
	Index       int
}

// assignedPay reports whether an assignment row is an earning or a deduction (as opposed to a
// benefit): its component is in the Earnings or Deductions category.
func (in *runInputs) assignedPay(b *ent.EmployeeBenefit) bool {
	if b.ComponentID == nil {
		return false
	}
	rc, ok := in.components[*b.ComponentID]
	if !ok || rc.Component == nil {
		return false
	}
	return rc.Component.Category == payrollsettings.CategoryEarnings || rc.Component.Category == payrollsettings.CategoryDeductions
}

// applyAssignedComponents adds the employee's assigned earnings and deductions for the period to
// the engine input and the payslip items. Rules:
//   - only assignments whose months cover the period, on components the tenant has switched on
//     (switching a component off stops it for every employee it was assigned to) and that are
//     neither statutory nor driven by their own module;
//   - a percentage applies to basic pay, or to gross pay (basic plus the fixed and basic-based
//     earnings assigned here) when the assignment says so;
//   - a taxable earning is a taxable allowance (gross, statutory and PAYE); a non-taxable one adds
//     to gross and net pay only;
//   - a deduction comes off net pay after the statutory deductions, PAYE and the recoverables, in
//     its phase and priority order, capped at the net pay left. Pension and provident fund
//     count for the pension relief, an insurance premium for the insurance relief.
func (in *runInputs) applyAssignedComponents(p RunParams, empID uuid.UUID, basic decimal.Decimal, ei *payrollengine.EmployeeInput, items *EmployeeItemized) {
	type due struct {
		row   *ent.EmployeeBenefit
		rc    payrollsettings.ResolvedComponent
		terms payrollsettings.AssignmentTerms
	}
	var earnings, deductions []due
	for _, b := range in.benefits[empID] {
		if !in.assignedPay(b) || !dateActive(b.EffectiveDate, b.EndDate, p.Period) {
			continue
		}
		rc := in.components[*b.ComponentID]
		if !rc.Active || rc.Statutory || rc.ManagedBy != "" {
			continue
		}
		d := due{row: b, rc: rc, terms: payrollsettings.Terms(b, rc)}
		if rc.Component.Category == payrollsettings.CategoryEarnings {
			earnings = append(earnings, d)
		} else {
			deductions = append(deductions, d)
		}
	}
	// Stable display order: by title.
	byTitle := func(ds []due) {
		sort.SliceStable(ds, func(i, j int) bool { return ds[i].rc.Title < ds[j].rc.Title })
	}
	byTitle(earnings)
	byTitle(deductions)

	// Gross for percentage-of-gross items: basic plus the earnings that do not depend on gross.
	gross := basic
	amounts := make([]decimal.Decimal, len(earnings))
	for i, e := range earnings {
		if e.terms.Percentage.IsPositive() && e.terms.Base == payrollsettings.PercentOfGross {
			continue
		}
		amounts[i] = e.terms.For(basic, basic)
		gross = gross.Add(amounts[i])
	}
	for i, e := range earnings {
		if e.terms.Percentage.IsPositive() && e.terms.Base == payrollsettings.PercentOfGross {
			amounts[i] = e.terms.For(basic, gross)
		}
	}
	for i, e := range earnings {
		amt := amounts[i]
		if !amt.IsPositive() {
			continue
		}
		cid := e.rc.Component.ID
		line := LabeledAmount{ComponentID: &cid, Label: e.rc.Title, Amount: amt}
		if e.rc.Component.TaxableStatus == "nontaxable" {
			ei.NonTaxableEarnings = ei.NonTaxableEarnings.Add(amt)
		} else {
			ei.TaxableAllowances = ei.TaxableAllowances.Add(amt)
			line.Taxable = amt
		}
		items.Allowances = append(items.Allowances, line)
	}

	pension, premium := decimal.Zero, decimal.Zero
	for _, d := range deductions {
		amt := d.terms.For(basic, gross)
		if !amt.IsPositive() {
			continue
		}
		phase := d.rc.Component.DeductionPhase
		if phase == "" {
			phase = payrollengine.PhaseAfterPAYE
		}
		switch d.rc.Code {
		case "pension", "provident_fund":
			pension = pension.Add(amt)
		case "insurance_premium":
			premium = premium.Add(amt)
		}
		items.OtherDeductions = append(items.OtherDeductions, DeductionLine{
			ComponentID: d.rc.Component.ID, Code: d.rc.Code, Label: d.rc.Title, Phase: phase,
			Amount: amt, Index: len(ei.OtherDeductions),
		})
		ei.OtherDeductions = append(ei.OtherDeductions, payrollengine.Deduction{
			Phase: phase, Priority: d.rc.Component.DeductionPriority, Amount: amt,
		})
	}
	// The salary tab may already carry the same contribution for relief only, so the larger of
	// the two counts, never the sum.
	ei.PensionContribution = decimal.Max(ei.PensionContribution, pension)
	ei.InsurancePremium = decimal.Max(ei.InsurancePremium, premium)
}
