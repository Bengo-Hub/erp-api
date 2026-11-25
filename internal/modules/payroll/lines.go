package payroll

import (
	"context"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
	"github.com/Bengo-Hub/erp-api/internal/ent/recoveryline"
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

// RecoveryAlloc is the frozen recovery of one recoverable in a run: which recoverable
// (type + id) and how much was recovered this period. Persisted as a RecoveryLine so disburse
// can write the amount back to the recoverable exactly once.
type RecoveryAlloc struct {
	Type   string // loan | advance | loss_damage | staff_purchase
	ID     uuid.UUID
	Amount decimal.Decimal
}

// EmployeeItemized is the labelled per-employee config the engine consumes as aggregates but
// the payslip persists as individual lines.
type EmployeeItemized struct {
	Benefits       []LabeledAmount
	Loans          []LabeledAmount
	Advances       []LabeledAmount
	LossDamages    []LabeledAmount
	StaffPurchases []LabeledAmount
	// Recoveries is the per-recoverable recovered amount for this period (all types), used to
	// persist RecoveryLine snapshots for the disburse-time write-back.
	Recoveries []RecoveryAlloc
	// Attendance is the approved attendance deductions taken off gross this period, and
	// AttendanceIDs their rows (marked applied once the payslip is written).
	Attendance    []LabeledAmount
	AttendanceIDs []uuid.UUID
	// Earnings is overtime, holiday work and piece pay added to taxable gross this period, and
	// PieceOutputIDs the piece output rows (marked paid once the payslip is written).
	Earnings       []EarningLine
	PieceOutputIDs []uuid.UUID
	// Reimbursements are the non-taxable expense claims added to net pay (never to gross).
	Reimbursements []LabeledAmount
	// ClaimIDs are the expense claims, taxable or not, paid through this payslip (claims_payroll.go).
	ClaimIDs []uuid.UUID
	// Allowances are the opt-in earnings assigned to the employee (Taxable zero when the component
	// is non-taxable), and OtherDeductions the opt-in deductions (assigned_components.go).
	Allowances      []LabeledAmount
	OtherDeductions []DeductionLine
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
	// secReimbursement is a non-taxable expense claim repaid with net pay. It is not part of
	// gross, so earnings plus reimbursements minus deductions equals net pay.
	secReimbursement = "reimbursement"
	// secShortfall records the part of an assigned deduction net pay could not cover. It is
	// informational: breakdowns and reports do not count it.
	secShortfall = "deduction_shortfall"
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
	lines := composeLines(basic, res, items)
	if len(lines) == 0 {
		return nil
	}
	builders := make([]*ent.PayslipLineCreate, 0, len(lines))
	for i, l := range lines {
		b := s.orm.PayslipLine.Create().
			SetTenantID(tenantID).SetPayslipID(payslipID).
			SetSection(l.Section).SetCode(l.Code).SetLabel(l.Label).
			SetCashAmount(l.Cash).SetTaxableAmount(l.TaxableAmount).SetEmployerAmount(l.Employer).
			SetNonCash(l.NonCash).SetTaxable(l.Taxable).SetSortOrder(i)
		if l.Phase != "" {
			b = b.SetDeductionPhase(l.Phase)
		}
		if l.ComponentID != nil {
			b = b.SetComponentID(*l.ComponentID)
		}
		builders = append(builders, b)
	}
	return s.orm.PayslipLine.CreateBulk(builders...).Exec(ctx)
}

// ComposedLine is one itemised payslip line before it is stored.
type ComposedLine struct {
	Section, Code, Label          string
	Cash, TaxableAmount, Employer decimal.Decimal
	NonCash, Taxable              bool
	Phase                         string
	ComponentID                   *uuid.UUID
}

// composeLines builds the ordered payslip lines from the engine result and the employee's items.
// The stored payslip and the employee pay summary both use it, so they cannot differ.
func composeLines(basic decimal.Decimal, res payrollengine.PayslipResult, items EmployeeItemized) []ComposedLine {
	var lines []ComposedLine
	add := func(section, code, label string, cash, taxable, employer decimal.Decimal, nonCash, taxable_ bool, phase string, comp *uuid.UUID) {
		lines = append(lines, ComposedLine{Section: section, Code: code, Label: label, Cash: cash, TaxableAmount: taxable,
			Employer: employer, NonCash: nonCash, Taxable: taxable_, Phase: phase, ComponentID: comp})
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
	// Opt-in earnings assigned to the employee, under the component title the tenant sees.
	for _, a := range items.Allowances {
		add(secEarningCash, "earning", a.Label, a.Amount, a.Taxable, decimal.Zero, false, a.Taxable.IsPositive(), "", a.ComponentID)
	}
	// Overtime, holiday work and piece pay are taxable cash earnings.
	for _, e := range items.Earnings {
		add(secEarningCash, e.Code, e.Label, e.Amount, e.Amount, decimal.Zero, false, true, "", nil)
	}
	// Approved attendance deductions are pay not earned: negative cash earnings, so basic plus
	// earnings still adds up to the payslip's gross. When the engine capped them at gross, one
	// line carries the amount actually taken.
	if res.UnpaidTime.IsPositive() {
		listed := decimal.Zero
		for _, a := range items.Attendance {
			listed = listed.Add(a.Amount)
		}
		if listed.Equal(res.UnpaidTime) {
			for _, a := range items.Attendance {
				add(secEarningCash, "attendance_deduction", a.Label, a.Amount.Neg(), a.Amount.Neg(), decimal.Zero, false, true, "", nil)
			}
		} else {
			add(secEarningCash, "attendance_deduction", "Unpaid time (attendance)", res.UnpaidTime.Neg(), res.UnpaidTime.Neg(), decimal.Zero, false, true, "", nil)
		}
	}

	// Non-taxable expense claims repaid with net pay.
	for _, r := range items.Reimbursements {
		add(secReimbursement, claimEarningCode, r.Label, r.Amount, decimal.Zero, decimal.Zero, false, false, "", nil)
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
	if res.InsuranceRelief.IsPositive() {
		add(secRelief, "insurance_relief", "Insurance Relief", res.InsuranceRelief, decimal.Zero, decimal.Zero, false, false, "", nil)
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
	for _, sp := range items.StaffPurchases {
		add(secAfterPaye, "staff_purchase", sp.Label, sp.Amount, decimal.Zero, decimal.Zero, false, false, payrollengine.PhaseAfterPAYE, sp.ComponentID)
	}
	// Opt-in deductions assigned to the employee, at the amount the engine took (capped at the
	// net pay left). They sit with the non-statutory deductions whatever their phase. What could
	// not be taken is kept as an informational line that no total counts.
	for _, d := range items.OtherDeductions {
		taken := res.OtherDeductionsApplied[d.Index]
		code := d.Code
		if code == "" {
			code = "deduction"
		}
		cid := d.ComponentID
		if taken.IsPositive() {
			add(secAfterPaye, code, d.Label, taken, decimal.Zero, decimal.Zero, false, false, d.Phase, &cid)
		}
		if short := d.Amount.Sub(taken); short.IsPositive() {
			add(secShortfall, code, d.Label+" (not deducted)", short, decimal.Zero, decimal.Zero, false, false, d.Phase, &cid)
		}
	}

	// Employer contributions (not deducted from net; for muster roll / GL / P9).
	if res.NSSFEmployer.IsPositive() {
		add(secEmployer, "nssf_employer", "N.S.S.F. Employer", decimal.Zero, decimal.Zero, res.NSSFEmployer, false, false, "", nil)
	}
	if res.NITAEmployer.IsPositive() {
		add(secEmployer, "nita", "NITA Levy", decimal.Zero, decimal.Zero, res.NITAEmployer, false, false, "", nil)
	}

	return lines
}

// writeRecoveryLines freezes this run's per-recoverable recoveries as RecoveryLine snapshots for the
// payslip. It replaces only UNAPPLIED lines (a re-run before disburse re-snapshots), never touching
// lines already applied to a disbursed batch. The disburse step reads these and writes the amounts
// back to each recoverable exactly once.
func (s *Service) writeRecoveryLines(ctx context.Context, tenantID, payslipID, employeeID uuid.UUID, recs []RecoveryAlloc) error {
	if _, err := s.orm.RecoveryLine.Delete().
		Where(
			recoveryline.TenantID(tenantID),
			recoveryline.PayslipID(payslipID),
			recoveryline.Applied(false),
		).Exec(ctx); err != nil {
		return err
	}
	if len(recs) == 0 {
		return nil
	}
	builders := make([]*ent.RecoveryLineCreate, 0, len(recs))
	for _, r := range recs {
		if r.ID == uuid.Nil || !r.Amount.IsPositive() {
			continue
		}
		builders = append(builders, s.orm.RecoveryLine.Create().
			SetTenantID(tenantID).
			SetPayslipID(payslipID).
			SetEmployeeID(employeeID).
			SetRecoverableType(recoveryline.RecoverableType(r.Type)).
			SetRecoverableID(r.ID).
			SetAmount(r.Amount))
	}
	if len(builders) == 0 {
		return nil
	}
	return s.orm.RecoveryLine.CreateBulk(builders...).Exec(ctx)
}
