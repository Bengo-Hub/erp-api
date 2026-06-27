// Package payroll runs payroll generation (using payrollengine) and persists payslips,
// all tenant-isolated. Recoverable persistence is a separate atomic step from calc.
package payroll

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/advance"
	"github.com/Bengo-Hub/erp-api/internal/ent/contract"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebenefit"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeloan"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeprojectallocation"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/lossanddamage"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollcomponent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
)

// Service generates and stores payslips.
type Service struct {
	orm       *ent.Client
	settings  *payrollsettings.Service
	publisher *events.Publisher
}

func NewService(orm *ent.Client, settings *payrollsettings.Service) *Service {
	return &Service{orm: orm, settings: settings}
}

// WithPublisher wires the outbox event publisher so claim approval can emit
// erp.expense_claim.approved for treasury to post the reimbursement to the GL. Returns the
// service for chaining; optional (nil publisher = no event, approval still works).
func (s *Service) WithPublisher(p *events.Publisher) *Service {
	s.publisher = p
	return s
}

// RunParams controls a payroll run.
type RunParams struct {
	TenantID        uuid.UUID
	OutletID        uuid.UUID // uuid.Nil = all outlets
	DepartmentID    uuid.UUID // uuid.Nil = all departments
	RegionID        uuid.UUID // uuid.Nil = all regions
	ProjectID       uuid.UUID // uuid.Nil = all projects (else: only employees allocated to it)
	Period          time.Time // first of month
	EmployeeIDs     []uuid.UUID
	RecoverAdvances bool
	CreatedBy       uuid.UUID
	Persist         bool // true = generate (write payslips); false = preview only
}

// LineResult pairs an employee with their engine output.
type LineResult struct {
	EmployeeID uuid.UUID                   `json:"employee_id"`
	Result     payrollengine.PayslipResult `json:"result"`
	PayslipID  *uuid.UUID                  `json:"payslip_id,omitempty"`
}

// Run computes (and optionally persists) payslips for the matching employees. It builds
// the tenant-scoped engine config ONCE and fails loud if a required statutory formula is
// missing — aborting before any payslip is written (gaps §2.2).
func (s *Service) Run(ctx context.Context, p RunParams) ([]LineResult, error) {
	cfg, err := s.settings.BuildEngineConfig(ctx, p.TenantID, p.Period, p.RecoverAdvances)
	if err != nil {
		return nil, fmt.Errorf("payroll: config: %w", err)
	}

	emps, err := s.selectEmployees(ctx, p)
	if err != nil {
		return nil, err
	}

	out := make([]LineResult, 0, len(emps))
	for _, emp := range emps {
		in, items, ierr := s.buildEmployeeInput(ctx, p, emp)
		if ierr != nil {
			return nil, fmt.Errorf("payroll: employee %s: %w", emp.ID, ierr)
		}
		res, cerr := payrollengine.Compute(cfg, in)
		if cerr != nil {
			return nil, fmt.Errorf("payroll: employee %s: %w", emp.ID, cerr)
		}
		line := LineResult{EmployeeID: emp.ID, Result: res}
		if p.Persist {
			id, perr := s.persistPayslip(ctx, p, emp, res)
			if perr != nil {
				return nil, fmt.Errorf("payroll: persist %s: %w", emp.ID, perr)
			}
			line.PayslipID = &id
			// Itemised payslip lines (best-effort, additive): power the rich payslip PDF,
			// Muster Roll, Payroll Summary and P9. Failure must not abort the run.
			if lerr := s.writePayslipLines(ctx, p.TenantID, id, in.GrossPay, res, items); lerr != nil {
				return nil, fmt.Errorf("payroll: payslip lines %s: %w", emp.ID, lerr)
			}
		}
		out = append(out, line)
	}
	return out, nil
}

func (s *Service) selectEmployees(ctx context.Context, p RunParams) ([]*ent.Employee, error) {
	q := s.orm.Employee.Query().Where(
		employee.TenantID(p.TenantID),
		employee.Deleted(false),
		employee.Terminated(false),
	)
	if p.OutletID != uuid.Nil {
		q = q.Where(employee.OutletID(p.OutletID))
	}
	if len(p.EmployeeIDs) > 0 {
		q = q.Where(employee.IDIn(p.EmployeeIDs...))
	}
	// Department / Region live on hr_details — restrict to the matching employees.
	if p.DepartmentID != uuid.Nil || p.RegionID != uuid.Nil {
		hq := s.orm.HRDetails.Query().Where(hrdetails.TenantID(p.TenantID))
		if p.DepartmentID != uuid.Nil {
			hq = hq.Where(hrdetails.DepartmentID(p.DepartmentID))
		}
		if p.RegionID != uuid.Nil {
			hq = hq.Where(hrdetails.RegionID(p.RegionID))
		}
		hrs, err := hq.All(ctx)
		if err != nil {
			return nil, fmt.Errorf("payroll: filter dept/region: %w", err)
		}
		ids := make([]uuid.UUID, len(hrs))
		for i, h := range hrs {
			ids[i] = h.EmployeeID
		}
		q = q.Where(employee.IDIn(ids...))
	}
	// Project filter — only employees with an ACTIVE allocation to the project for the period.
	if p.ProjectID != uuid.Nil {
		allocs, err := s.orm.EmployeeProjectAllocation.Query().
			Where(
				employeeprojectallocation.TenantID(p.TenantID),
				employeeprojectallocation.ProjectID(p.ProjectID),
				employeeprojectallocation.IsActive(true),
			).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("payroll: filter project: %w", err)
		}
		ids := make([]uuid.UUID, len(allocs))
		for i, a := range allocs {
			ids[i] = a.EmployeeID
		}
		q = q.Where(employee.IDIn(ids...))
	}
	candidates, err := q.All(ctx)
	if err != nil || len(candidates) == 0 {
		return candidates, err
	}
	return s.gateByContractAndType(ctx, p, candidates)
}

// gateByContractAndType applies the standard payroll-eligibility rules (decision 2026-06-26):
// permanent (or unspecified) employees are always on PAYE payroll; fixed-term "contract" employees
// are included only when an ACTIVE contract covers the period; "casual" workers are excluded (paid
// via the casual-labour module) and "consultant" engagements are excluded (paid via WHT/AP, not
// PAYE). Employees skipped here are recorded in s.lastSkipped for the run summary.
func (s *Service) gateByContractAndType(ctx context.Context, p RunParams, candidates []*ent.Employee) ([]*ent.Employee, error) {
	ids := make([]uuid.UUID, len(candidates))
	for i, e := range candidates {
		ids[i] = e.ID
	}
	// Employment type per employee (from hr_details).
	etype := map[uuid.UUID]string{}
	hrs, err := s.orm.HRDetails.Query().
		Where(hrdetails.TenantID(p.TenantID), hrdetails.EmployeeIDIn(ids...)).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, h := range hrs {
		etype[h.EmployeeID] = strings.ToLower(strings.TrimSpace(h.EmploymentType))
	}
	// Employees with an active contract covering the period.
	activeContract := map[uuid.UUID]bool{}
	cons, err := s.orm.Contract.Query().
		Where(contract.TenantID(p.TenantID), contract.EmployeeIDIn(ids...), contract.Status("active")).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, c := range cons {
		if contractCovers(c, p.Period) {
			activeContract[c.EmployeeID] = true
		}
	}

	out := make([]*ent.Employee, 0, len(candidates))
	for _, e := range candidates {
		switch etype[e.ID] {
		case "casual", "consultant":
			// casual -> casual-labour module; consultant -> WHT/AP, not PAYE payroll.
		case "contract":
			if activeContract[e.ID] { // fixed-term needs an active contract covering the period
				out = append(out, e)
			}
		default: // permanent or unspecified -> always on payroll
			out = append(out, e)
		}
	}
	return out, nil
}

// contractCovers reports whether an active contract spans the payroll period (open-ended start/end
// are treated as covering).
func contractCovers(c *ent.Contract, period time.Time) bool {
	if c.StartDate != nil && c.StartDate.After(period) {
		return false
	}
	if c.EndDate != nil && c.EndDate.Before(period) {
		return false
	}
	return true
}

// buildEmployeeInput loads salary + active, effective-dated recoverables for the employee
// and maps them to the pure engine input (no persistence — gaps §2.7).
func (s *Service) buildEmployeeInput(ctx context.Context, p RunParams, emp *ent.Employee) (payrollengine.EmployeeInput, EmployeeItemized, error) {
	var in payrollengine.EmployeeInput
	var items EmployeeItemized

	sal, err := s.orm.SalaryDetails.Query().
		Where(salarydetails.TenantID(p.TenantID), salarydetails.EmployeeID(emp.ID), salarydetails.IsActive(true)).
		First(ctx)
	if ent.IsNotFound(err) {
		return in, items, fmt.Errorf("no active salary details")
	}
	if err != nil {
		return in, items, err
	}
	in.GrossPay = sal.MonthlySalary
	in.TaxCategory = sal.IncomeTax

	// Loans: recover min(installment, outstanding) for active, period-effective loans.
	loans, err := s.orm.EmployeeLoan.Query().
		Where(employeeloan.TenantID(p.TenantID), employeeloan.EmployeeID(emp.ID), employeeloan.IsActive(true)).
		All(ctx)
	if err != nil {
		return in, items, err
	}
	for _, l := range loans {
		if !dateActive(l.StartDate, l.EndDate, p.Period) {
			continue
		}
		outstanding := l.PrincipalAmount.Sub(l.AmountRepaid)
		in.Loans = append(in.Loans, payrollengine.Recoverable{Installment: l.MonthlyInstallment, Outstanding: outstanding})
		if rec := recovered(l.MonthlyInstallment, outstanding); rec.IsPositive() {
			items.Loans = append(items.Loans, LabeledAmount{Label: "Loan", Amount: rec})
		}
	}

	// Advances.
	advs, err := s.orm.Advance.Query().
		Where(advance.TenantID(p.TenantID), advance.EmployeeID(emp.ID), advance.IsActive(true)).
		All(ctx)
	if err != nil {
		return in, items, err
	}
	for _, a := range advs {
		if a.IssueDate != nil && a.IssueDate.After(p.Period) {
			continue
		}
		install, e := s.installmentFor(ctx, a.RepayOptionID)
		if e != nil {
			return in, items, e
		}
		outstanding := a.AmountIssued.Sub(a.AmountRepaid)
		in.Advances = append(in.Advances, payrollengine.Recoverable{Installment: install, Outstanding: outstanding})
		if p.RecoverAdvances {
			if rec := recovered(install, outstanding); rec.IsPositive() {
				items.Advances = append(items.Advances, LabeledAmount{Label: "Salary Advance", Amount: rec})
			}
		}
	}

	// Loss/damages.
	lds, err := s.orm.LossAndDamage.Query().
		Where(lossanddamage.TenantID(p.TenantID), lossanddamage.EmployeeID(emp.ID), lossanddamage.IsActive(true)).
		All(ctx)
	if err != nil {
		return in, items, err
	}
	for _, ld := range lds {
		if ld.IssueDate != nil && ld.IssueDate.After(p.Period) {
			continue
		}
		install, e := s.installmentFor(ctx, ld.RepayOptionID)
		if e != nil {
			return in, items, e
		}
		outstanding := ld.DamageAmount.Sub(ld.AmountRepaid)
		in.LossDamages = append(in.LossDamages, payrollengine.Recoverable{Installment: install, Outstanding: outstanding})
		if rec := recovered(install, outstanding); rec.IsPositive() {
			items.LossDamages = append(items.LossDamages, LabeledAmount{Label: "Loss & Damage", Amount: rec})
		}
	}

	// Non-cash benefits (fed to the engine as an aggregate; itemised for the payslip lines).
	bens, err := s.orm.EmployeeBenefit.Query().
		Where(employeebenefit.TenantID(p.TenantID), employeebenefit.EmployeeID(emp.ID), employeebenefit.IsActive(true), employeebenefit.NonCash(true)).
		All(ctx)
	if err != nil {
		return in, items, err
	}
	total := decimal.Zero
	titles := s.componentTitles(ctx, p.TenantID, bens)
	for _, b := range bens {
		if !dateActive(b.EffectiveDate, b.EndDate, p.Period) {
			continue
		}
		total = total.Add(b.Amount)
		label := "Benefit"
		if b.ComponentID != nil {
			if t, ok := titles[*b.ComponentID]; ok {
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

// recovered returns the amount actually recovered this period: min(installment, outstanding),
// or zero when either is non-positive (mirrors payrollengine.sumRecoverables).
func recovered(installment, outstanding decimal.Decimal) decimal.Decimal {
	if installment.LessThanOrEqual(decimal.Zero) || outstanding.LessThanOrEqual(decimal.Zero) {
		return decimal.Zero
	}
	if installment.LessThan(outstanding) {
		return installment
	}
	return outstanding
}

// componentTitles batch-loads the titles for the benefit components referenced by bens.
func (s *Service) componentTitles(ctx context.Context, tenantID uuid.UUID, bens []*ent.EmployeeBenefit) map[uuid.UUID]string {
	ids := make([]uuid.UUID, 0, len(bens))
	for _, b := range bens {
		if b.ComponentID != nil {
			ids = append(ids, *b.ComponentID)
		}
	}
	out := map[uuid.UUID]string{}
	if len(ids) == 0 {
		return out
	}
	rows, err := s.orm.PayrollComponent.Query().Where(payrollcomponent.IDIn(ids...)).All(ctx)
	if err != nil {
		return out
	}
	for _, c := range rows {
		out[c.ID] = c.Title
	}
	return out
}

// installmentFor resolves the per-period installment for a repay option (amount/installments).
func (s *Service) installmentFor(ctx context.Context, repayOptionID *uuid.UUID) (decimal.Decimal, error) {
	if repayOptionID == nil {
		return decimal.Zero, nil
	}
	ro, err := s.orm.RepayOption.Get(ctx, *repayOptionID)
	if ent.IsNotFound(err) {
		return decimal.Zero, nil
	}
	if err != nil {
		return decimal.Zero, err
	}
	if ro.NoOfInstallments <= 0 {
		return decimal.Zero, nil
	}
	return ro.Amount.DivRound(decimal.NewFromInt(int64(ro.NoOfInstallments)), 4), nil
}

// persistPayslip upserts the payslip for (employee, period) and writes the engine output.
func (s *Service) persistPayslip(ctx context.Context, p RunParams, emp *ent.Employee, res payrollengine.PayslipResult) (uuid.UUID, error) {
	existing, err := s.orm.Payslip.Query().
		Where(
			payslip.TenantID(p.TenantID),
			payslip.EmployeeID(emp.ID),
			payslip.PaymentPeriod(p.Period),
			payslip.DeleteStatus(false),
		).First(ctx)

	if ent.IsNotFound(err) {
		c := s.orm.Payslip.Create().
			SetTenantID(p.TenantID).
			SetEmployeeID(emp.ID).
			SetPaymentPeriod(p.Period).
			SetPayrollStatus("complete").
			SetApprovalStatus("draft").
			SetGrossPay(res.GrossPay).
			SetTaxablePay(res.TaxablePay).
			SetPaye(res.PAYE).
			SetTaxRelief(res.PersonalRelief).
			SetReliefs(res.PersonalRelief).
			SetGrossPayAfterTax(res.GrossPayAfterTax).
			SetShifOrNhifContribution(res.SHIFOrNHIF).
			SetHousingLevy(res.HousingLevy).
			SetNssfEmployeeTier1(res.NSSFEmployeeTier1).
			SetNssfEmployeeTier2(res.NSSFEmployeeTier2).
			SetNssfEmployerContribution(res.NSSFEmployer).
			SetDeductionsBeforeTax(res.DeductionsBeforeTax).
			SetDeductionsAfterTax(res.DeductionsAfterTax).
			SetDeductionsAfterPaye(res.DeductionsAfterPAYE).
			SetDeductionsFinal(res.DeductionsFinal).
			SetNetPay(res.NetPay)
		if emp.OutletID != nil {
			c = c.SetOutletID(*emp.OutletID)
		}
		if p.CreatedBy != uuid.Nil {
			c = c.SetCreatedBy(p.CreatedBy)
		}
		row, cerr := c.Save(ctx)
		if cerr != nil {
			return uuid.Nil, cerr
		}
		return row.ID, nil
	}
	if err != nil {
		return uuid.Nil, err
	}

	row, uerr := existing.Update().
		SetPayrollStatus("complete").
		SetGrossPay(res.GrossPay).
		SetTaxablePay(res.TaxablePay).
		SetPaye(res.PAYE).
		SetTaxRelief(res.PersonalRelief).
		SetReliefs(res.PersonalRelief).
		SetGrossPayAfterTax(res.GrossPayAfterTax).
		SetShifOrNhifContribution(res.SHIFOrNHIF).
		SetHousingLevy(res.HousingLevy).
		SetNssfEmployeeTier1(res.NSSFEmployeeTier1).
		SetNssfEmployeeTier2(res.NSSFEmployeeTier2).
		SetNssfEmployerContribution(res.NSSFEmployer).
		SetDeductionsBeforeTax(res.DeductionsBeforeTax).
		SetDeductionsAfterTax(res.DeductionsAfterTax).
		SetDeductionsAfterPaye(res.DeductionsAfterPAYE).
		SetDeductionsFinal(res.DeductionsFinal).
		SetNetPay(res.NetPay).
		Save(ctx)
	if uerr != nil {
		return uuid.Nil, uerr
	}
	return row.ID, nil
}

// dateActive reports whether period falls within [start, end] (nil bounds are open).
func dateActive(start, end *time.Time, period time.Time) bool {
	if start != nil && period.Before(*start) {
		return false
	}
	if end != nil && period.After(*end) {
		return false
	}
	return true
}
