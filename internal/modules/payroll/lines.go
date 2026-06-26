package payroll

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// LabeledAmount is one itemised input line carried from the employee's config to the
// persisted payslip (so the payslip shows "House Allowance", "Company Loan", etc. instead
// of a single lumped figure).
type LabeledAmount struct {
	ComponentID *uuid.UUID
	Label       string
	Amount      decimal.Decimal // cash value
	Taxable     decimal.Decimal // taxable/effective value (== Amount unless a fringe value applies)
	NonCash     bool
}

// EmployeeItemized is the labelled per-employee config the engine consumes as aggregates but
// the payslip persists as individual lines.
type EmployeeItemized struct {
	Benefits    []LabeledAmount
	Loans       []LabeledAmount
	Advances    []LabeledAmount
	LossDamages []LabeledAmount
}

// payslip_line sections (mirror schema).
const (
	secEarningCash    = "earning_cash"
	secBenefitNonCash = "benefit_noncash"
	secBeforeTax      = "deduction_before_tax"
	secTax            = "tax"
	secRelief         = "relief"
	secAfterPaye      = "deduction_after_tax"
	secEmployer       = "employer_contribution"
)

// LoadPayslipLines returns a payslip's itemised lines in display order (empty for old payslips).
func (s *Service) LoadPayslipLines(ctx context.Context, tenantID, payslipID uuid.UUID) ([]*ent.PayslipLine, error) {
	return s.orm.PayslipLine.Query().
		Where(payslipline.TenantID(tenantID), payslipline.PayslipID(payslipID)).
		Order(ent.Asc(payslipline.FieldSortOrder)).All(ctx)
}

// writePayslipLines replaces the itemised lines for a payslip (delete + recreate so a re-run
// is clean). It composes the ordered set from the engine result (statutory + employer side)
// and the labelled employee config (basic pay, benefits, loans/advances/loss). Best-effort
// detail: it never changes the persisted totals on the payslip row.
func (s *Service) writePayslipLines(ctx context.Context, tenantID, payslipID uuid.UUID, basic decimal.Decimal, res payrollengine.PayslipResult, items EmployeeItemized) error {
	if _, err := s.orm.PayslipLine.Delete().
		Where(payslipline.TenantID(tenantID), payslipline.PayslipID(payslipID)).Exec(ctx); err != nil {
		return err
	}

	var builders []*ent.PayslipLineCreate
	order := 0
	add := func(section, code, label string, cash, taxable, employer decimal.Decimal, nonCash, taxable_ bool, phase string, comp *uuid.UUID) {
		b := s.orm.PayslipLine.Create().
			SetTenantID(tenantID).SetPayslipID(payslipID).
			SetSection(section).SetCode(code).SetLabel(label).
			SetCashAmount(cash).SetTaxableAmount(taxable).SetEmployerAmount(employer).
			SetNonCash(nonCash).SetTaxable(taxable_).SetSortOrder(order)
		if phase != "" {
			b = b.SetDeductionPhase(phase)
		}
		if comp != nil {
			b = b.SetComponentID(*comp)
		}
		builders = append(builders, b)
		order++
	}

	// Earnings: basic pay (cash) then each benefit/allowance.
	if basic.IsPositive() {
		add(secEarningCash, "basic", "Basic Pay", basic, basic, decimal.Zero, false, true, "", nil)
	}
	for _, b := range items.Benefits {
		sec := secEarningCash
		if b.NonCash {
			sec = secBenefitNonCash
		}
		add(sec, "benefit", b.Label, b.Amount, b.Taxable, decimal.Zero, b.NonCash, true, "", b.ComponentID)
	}

	// Statutory (before-tax) — NSSF split into tiers + employer, SHIF, housing levy.
	if res.NSSFEmployeeTier1.IsPositive() {
		add(secBeforeTax, "nssf_t1", "N.S.S.F. Tier I", res.NSSFEmployeeTier1, decimal.Zero, decimal.Zero, false, false, payrollengine.PhaseBeforeTax, nil)
	}
	if res.NSSFEmployeeTier2.IsPositive() {
		add(secBeforeTax, "nssf_t2", "N.S.S.F. Tier II", res.NSSFEmployeeTier2, decimal.Zero, decimal.Zero, false, false, payrollengine.PhaseBeforeTax, nil)
	}
	if res.SHIFOrNHIF.IsPositive() {
		add(secBeforeTax, "shif", "S.H.I.F.", res.SHIFOrNHIF, decimal.Zero, decimal.Zero, false, false, payrollengine.PhaseBeforeTax, nil)
	}
	if res.HousingLevy.IsPositive() {
		add(secBeforeTax, "housing_levy", "Housing Levy", res.HousingLevy, decimal.Zero, decimal.Zero, false, false, payrollengine.PhaseBeforeTax, nil)
	}

	// Tax + relief.
	if res.PersonalRelief.IsPositive() {
		add(secRelief, "personal_relief", "Personal Relief", res.PersonalRelief, decimal.Zero, decimal.Zero, false, false, "", nil)
	}
	if res.PAYE.IsPositive() {
		add(secTax, "paye", "P.A.Y.E.", res.PAYE, decimal.Zero, decimal.Zero, false, false, payrollengine.PhaseAfterTax, nil)
	}

	// After-PAYE recoverables (labelled).
	for _, l := range items.Loans {
		add(secAfterPaye, "loan", l.Label, l.Amount, decimal.Zero, decimal.Zero, false, false, payrollengine.PhaseAfterPAYE, l.ComponentID)
	}
	for _, a := range items.Advances {
		add(secAfterPaye, "advance", a.Label, a.Amount, decimal.Zero, decimal.Zero, false, false, payrollengine.PhaseAfterPAYE, a.ComponentID)
	}
	for _, d := range items.LossDamages {
		add(secAfterPaye, "loss_damage", d.Label, d.Amount, decimal.Zero, decimal.Zero, false, false, payrollengine.PhaseAfterPAYE, d.ComponentID)
	}

	// Employer contributions (not deducted from net; for muster roll / GL / P9).
	if res.NSSFEmployer.IsPositive() {
		add(secEmployer, "nssf_employer", "N.S.S.F. Employer", decimal.Zero, decimal.Zero, res.NSSFEmployer, false, false, "", nil)
	}

	if len(builders) == 0 {
		return nil
	}
	return s.orm.PayslipLine.CreateBulk(builders...).Exec(ctx)
}
