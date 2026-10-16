package payroll

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/advance"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebenefit"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeloan"
	"github.com/Bengo-Hub/erp-api/internal/ent/lossanddamage"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollcomponent"
	"github.com/Bengo-Hub/erp-api/internal/ent/repayoption"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/staffpurchasededuction"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// runChunk bounds each IN (...) list so a large payroll never builds an oversized query.
const runChunk = 1000

// runInputs is everything buildEmployeeInput reads, loaded once per run: a fixed handful of
// grouped reads per 1000 employees instead of seven or more queries per employee.
type runInputs struct {
	salaries       map[uuid.UUID]*ent.SalaryDetails
	loans          map[uuid.UUID][]*ent.EmployeeLoan
	advances       map[uuid.UUID][]*ent.Advance
	lossDamages    map[uuid.UUID][]*ent.LossAndDamage
	staffPurchases map[uuid.UUID][]*ent.StaffPurchaseDeduction
	benefits       map[uuid.UUID][]*ent.EmployeeBenefit
	installments   map[uuid.UUID]decimal.Decimal // repay option id -> per-period installment
	titles         map[uuid.UUID]string          // payroll component id -> title
}

// loadRunInputs reads salaries, active recoverables, non-cash benefits, their repay options and
// component titles for the run's employees.
func (s *Service) loadRunInputs(ctx context.Context, tenantID uuid.UUID, emps []*ent.Employee) (*runInputs, error) {
	in := &runInputs{
		salaries:       map[uuid.UUID]*ent.SalaryDetails{},
		loans:          map[uuid.UUID][]*ent.EmployeeLoan{},
		advances:       map[uuid.UUID][]*ent.Advance{},
		lossDamages:    map[uuid.UUID][]*ent.LossAndDamage{},
		staffPurchases: map[uuid.UUID][]*ent.StaffPurchaseDeduction{},
		benefits:       map[uuid.UUID][]*ent.EmployeeBenefit{},
		installments:   map[uuid.UUID]decimal.Decimal{},
		titles:         map[uuid.UUID]string{},
	}
	repayIDs := map[uuid.UUID]bool{}
	componentIDs := map[uuid.UUID]bool{}
	for start := 0; start < len(emps); start += runChunk {
		end := min(start+runChunk, len(emps))
		ids := make([]uuid.UUID, 0, end-start)
		for _, e := range emps[start:end] {
			ids = append(ids, e.ID)
		}

		// Newest active salary row wins when an employee has more than one.
		sals, err := s.orm.SalaryDetails.Query().
			Where(salarydetails.TenantID(tenantID), salarydetails.EmployeeIDIn(ids...), salarydetails.IsActive(true)).
			Order(ent.Desc(salarydetails.FieldCreatedAt)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("salaries: %w", err)
		}
		for _, sd := range sals {
			if _, ok := in.salaries[sd.EmployeeID]; !ok {
				in.salaries[sd.EmployeeID] = sd
			}
		}

		loans, err := s.orm.EmployeeLoan.Query().
			Where(employeeloan.TenantID(tenantID), employeeloan.EmployeeIDIn(ids...), employeeloan.IsActive(true)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("loans: %w", err)
		}
		for _, l := range loans {
			in.loans[l.EmployeeID] = append(in.loans[l.EmployeeID], l)
		}

		advs, err := s.orm.Advance.Query().
			Where(advance.TenantID(tenantID), advance.EmployeeIDIn(ids...), advance.IsActive(true)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("advances: %w", err)
		}
		for _, a := range advs {
			in.advances[a.EmployeeID] = append(in.advances[a.EmployeeID], a)
			if a.RepayOptionID != nil {
				repayIDs[*a.RepayOptionID] = true
			}
		}

		lds, err := s.orm.LossAndDamage.Query().
			Where(lossanddamage.TenantID(tenantID), lossanddamage.EmployeeIDIn(ids...), lossanddamage.IsActive(true)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("loss and damage: %w", err)
		}
		for _, ld := range lds {
			in.lossDamages[ld.EmployeeID] = append(in.lossDamages[ld.EmployeeID], ld)
			if ld.RepayOptionID != nil {
				repayIDs[*ld.RepayOptionID] = true
			}
		}

		sps, err := s.orm.StaffPurchaseDeduction.Query().
			Where(staffpurchasededuction.TenantID(tenantID), staffpurchasededuction.EmployeeIDIn(ids...), staffpurchasededuction.IsActive(true)).
			All(ctx)
		if err != nil {
			return nil, fmt.Errorf("staff purchases: %w", err)
		}
		for _, sp := range sps {
			in.staffPurchases[sp.EmployeeID] = append(in.staffPurchases[sp.EmployeeID], sp)
		}

		bens, err := s.orm.EmployeeBenefit.Query().
			Where(employeebenefit.TenantID(tenantID), employeebenefit.EmployeeIDIn(ids...),
				employeebenefit.IsActive(true), employeebenefit.NonCash(true)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("benefits: %w", err)
		}
		for _, b := range bens {
			in.benefits[b.EmployeeID] = append(in.benefits[b.EmployeeID], b)
			if b.ComponentID != nil {
				componentIDs[*b.ComponentID] = true
			}
		}
	}

	// Installment per repay option: amount / number of installments (zero when unset).
	for _, chunk := range chunkIDs(repayIDs) {
		opts, err := s.orm.RepayOption.Query().Where(repayoption.IDIn(chunk...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("repay options: %w", err)
		}
		for _, ro := range opts {
			if ro.NoOfInstallments > 0 {
				in.installments[ro.ID] = ro.Amount.DivRound(decimal.NewFromInt(int64(ro.NoOfInstallments)), 4)
			}
		}
	}
	for _, chunk := range chunkIDs(componentIDs) {
		rows, err := s.orm.PayrollComponent.Query().Where(payrollcomponent.IDIn(chunk...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("payroll components: %w", err)
		}
		for _, c := range rows {
			in.titles[c.ID] = c.Title
		}
	}
	return in, nil
}

func chunkIDs(set map[uuid.UUID]bool) [][]uuid.UUID {
	var out [][]uuid.UUID
	cur := make([]uuid.UUID, 0, min(len(set), runChunk))
	for id := range set {
		cur = append(cur, id)
		if len(cur) == runChunk {
			out = append(out, cur)
			cur = make([]uuid.UUID, 0, runChunk)
		}
	}
	if len(cur) > 0 {
		out = append(out, cur)
	}
	return out
}

func (in *runInputs) installment(repayOptionID *uuid.UUID) decimal.Decimal {
	if repayOptionID == nil {
		return decimal.Zero
	}
	return in.installments[*repayOptionID] // zero when the option is missing or has no installments
}

// buildEmployeeInput maps an employee's salary and active, effective-dated recoverables and
// benefits (preloaded for the run) to the pure engine input. No persistence (gaps §2.7).
func (s *Service) buildEmployeeInput(p RunParams, emp *ent.Employee, pre *runInputs) (payrollengine.EmployeeInput, EmployeeItemized, error) {
	var in payrollengine.EmployeeInput
	var items EmployeeItemized

	sal, ok := pre.salaries[emp.ID]
	if !ok {
		return in, items, fmt.Errorf("no active salary details")
	}
	in.GrossPay = sal.MonthlySalary
	in.TaxCategory = sal.IncomeTax
	// Per-employee KRA relief inputs (actual monthly amounts; the engine applies the statutory caps).
	in.InsurancePremium = sal.InsurancePremium
	in.PensionContribution = sal.PensionContribution
	in.MortgageInterest = sal.MortgageInterest
	in.DisabilityExempt = sal.DisabilityExempt

	// Loans: recover min(installment, outstanding) for active, period-effective loans.
	for _, l := range pre.loans[emp.ID] {
		if !dateActive(l.StartDate, l.EndDate, p.Period) {
			continue
		}
		outstanding := l.PrincipalAmount.Sub(l.AmountRepaid)
		in.Loans = append(in.Loans, payrollengine.Recoverable{Installment: l.MonthlyInstallment, Outstanding: outstanding})
		if rec := recovered(l.MonthlyInstallment, outstanding); rec.IsPositive() {
			items.Loans = append(items.Loans, LabeledAmount{Label: "Loan", Amount: rec})
			items.Recoveries = append(items.Recoveries, RecoveryAlloc{Type: "loan", ID: l.ID, Amount: rec})
		}
	}

	// Advances (recovered only when the run asks for it).
	for _, a := range pre.advances[emp.ID] {
		if a.IssueDate != nil && a.IssueDate.After(p.Period) {
			continue
		}
		install := pre.installment(a.RepayOptionID)
		outstanding := a.AmountIssued.Sub(a.AmountRepaid)
		in.Advances = append(in.Advances, payrollengine.Recoverable{Installment: install, Outstanding: outstanding})
		if p.RecoverAdvances {
			if rec := recovered(install, outstanding); rec.IsPositive() {
				items.Advances = append(items.Advances, LabeledAmount{Label: "Salary Advance", Amount: rec})
				items.Recoveries = append(items.Recoveries, RecoveryAlloc{Type: "advance", ID: a.ID, Amount: rec})
			}
		}
	}

	// Loss/damages.
	for _, ld := range pre.lossDamages[emp.ID] {
		if ld.IssueDate != nil && ld.IssueDate.After(p.Period) {
			continue
		}
		install := pre.installment(ld.RepayOptionID)
		outstanding := ld.DamageAmount.Sub(ld.AmountRepaid)
		in.LossDamages = append(in.LossDamages, payrollengine.Recoverable{Installment: install, Outstanding: outstanding})
		if rec := recovered(install, outstanding); rec.IsPositive() {
			items.LossDamages = append(items.LossDamages, LabeledAmount{Label: "Loss & Damage", Amount: rec})
			items.Recoveries = append(items.Recoveries, RecoveryAlloc{Type: "loss_damage", ID: ld.ID, Amount: rec})
		}
	}

	// Staff purchases (POS credit/layaway funded from salary), recovered like other recoverables.
	for _, sp := range pre.staffPurchases[emp.ID] {
		outstanding := sp.Principal.Sub(sp.AmountRecovered)
		in.StaffPurchases = append(in.StaffPurchases, payrollengine.Recoverable{Installment: sp.InstallmentAmount, Outstanding: outstanding})
		if rec := recovered(sp.InstallmentAmount, outstanding); rec.IsPositive() {
			items.StaffPurchases = append(items.StaffPurchases, LabeledAmount{Label: "Staff Purchase", Amount: rec})
			items.Recoveries = append(items.Recoveries, RecoveryAlloc{Type: "staff_purchase", ID: sp.ID, Amount: rec})
		}
	}

	// Non-cash benefits (fed to the engine as an aggregate; itemised for the payslip lines).
	total := decimal.Zero
	for _, b := range pre.benefits[emp.ID] {
		if !dateActive(b.EffectiveDate, b.EndDate, p.Period) {
			continue
		}
		total = total.Add(b.Amount)
		label := "Benefit"
		if b.ComponentID != nil {
			if t, ok := pre.titles[*b.ComponentID]; ok {
				label = t
			}
		}
		items.Benefits = append(items.Benefits, LabeledAmount{
			ComponentID: b.ComponentID, Label: label, Amount: b.Amount, Taxable: b.Amount, NonCash: true,
		})
	}
	in.NonCashBenefits = total
	return in, items, nil
}
