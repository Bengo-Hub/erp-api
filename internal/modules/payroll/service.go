// Package payroll runs payroll generation (using payrollengine) and persists payslips,
// all tenant-isolated. Recoverable persistence is a separate atomic step from calc.
package payroll

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/contract"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeprojectallocation"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
)

// errPayslipLocked marks a payslip a re-run must not change: it is posted for payment or paid.
var errPayslipLocked = errors.New("payroll: payslip is posted for payment")

// Service generates and stores payslips.
type Service struct {
	orm       *ent.Client
	settings  *payrollsettings.Service
	publisher *events.Publisher
	log       *zap.Logger
	budgets   BudgetChecker
	approvals ApprovalEngine // run approval (payslip_approval.go)
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
	// OnProgress, when set, is called with (0, total) before the first employee and after each
	// one, so a background run can report progress.
	OnProgress func(done, total int)
}

// LineResult pairs an employee with their engine output.
type LineResult struct {
	EmployeeID uuid.UUID                   `json:"employee_id"`
	Result     payrollengine.PayslipResult `json:"result"`
	PayslipID  *uuid.UUID                  `json:"payslip_id,omitempty"`
	// Lines are the itemised payslip lines of the result (the ones a persisted run stores).
	Lines []ComposedLine `json:"-"`
}

// Run computes (and optionally persists) payslips for the matching employees. It builds
// the tenant-scoped engine config ONCE and fails loud if a required statutory formula is
// missing — aborting before any payslip is written.
func (s *Service) Run(ctx context.Context, p RunParams) ([]LineResult, error) {
	cfg, err := s.settings.BuildEngineConfig(ctx, p.TenantID, p.Period, p.RecoverAdvances)
	if err != nil {
		return nil, fmt.Errorf("payroll: config: %w", err)
	}

	emps, err := s.selectEmployees(ctx, p)
	if err != nil {
		return nil, err
	}
	// Everything the engine input needs, and the month's approved attendance deductions, are
	// loaded once for the whole run rather than per employee.
	pre, err := s.loadRunInputs(ctx, p.TenantID, emps)
	if err != nil {
		return nil, fmt.Errorf("payroll: load inputs: %w", err)
	}
	attendance, err := s.approvedAttendanceDeductions(ctx, p.TenantID, p.Period)
	if err != nil {
		return nil, fmt.Errorf("payroll: attendance deductions: %w", err)
	}
	// Overtime, holiday work and approved piece output are paid as taxable cash earnings.
	earnings, err := s.loadAttendanceEarnings(ctx, p, emps)
	if err != nil {
		return nil, fmt.Errorf("payroll: attendance earnings: %w", err)
	}
	// Approved taxable expense claims are paid through the payslip as taxable earnings.
	claims, err := s.loadPayrollClaims(ctx, p.TenantID, p.Period, emps)
	if err != nil {
		return nil, err
	}
	if p.OnProgress != nil {
		p.OnProgress(0, len(emps))
	}

	out := make([]LineResult, 0, len(emps))
	for i, emp := range emps {
		if err := ctx.Err(); err != nil {
			return nil, err
		}
		in, items, ierr := s.buildEmployeeInput(p, emp, pre)
		if ierr != nil {
			return nil, fmt.Errorf("payroll: employee %s: %w", emp.ID, ierr)
		}
		for _, d := range attendance[emp.ID] {
			in.UnpaidTime = in.UnpaidTime.Add(d.Amount)
			items.Attendance = append(items.Attendance, LabeledAmount{Label: attendanceLabel(d), Amount: d.Amount})
			items.AttendanceIDs = append(items.AttendanceIDs, d.ID)
		}
		earnings.apply(emp.ID, &in, &items)
		applyClaims(claims[emp.ID], &in, &items)
		res, cerr := payrollengine.Compute(cfg, in)
		if cerr != nil {
			return nil, fmt.Errorf("payroll: employee %s: %w", emp.ID, cerr)
		}
		line := LineResult{EmployeeID: emp.ID, Result: res}
		if !p.Persist && len(p.EmployeeIDs) > 0 {
			line.Lines = composeLines(in.GrossPay, res, items)
		}
		if p.Persist {
			id, perr := s.persistPayslip(ctx, p, emp, res)
			if errors.Is(perr, errPayslipLocked) {
				// Posted or paid: leave the payslip and its lines as they are.
				line.PayslipID = &id
				out = append(out, line)
				if p.OnProgress != nil {
					p.OnProgress(i+1, len(emps))
				}
				continue
			}
			if perr != nil {
				return nil, fmt.Errorf("payroll: persist %s: %w", emp.ID, perr)
			}
			line.PayslipID = &id
			// Itemised payslip lines (best-effort, additive): power the rich payslip PDF,
			// Muster Roll, Payroll Summary and P9. Failure must not abort the run.
			if lerr := s.writePayslipLines(ctx, p.TenantID, id, in.GrossPay, res, items); lerr != nil {
				return nil, fmt.Errorf("payroll: payslip lines %s: %w", emp.ID, lerr)
			}
			// Freeze this period's per-recoverable recoveries so disburse can write them back
			// to each loan/advance/loss-damage/staff-purchase exactly once.
			if rerr := s.writeRecoveryLines(ctx, p.TenantID, id, emp.ID, items.Recoveries); rerr != nil {
				return nil, fmt.Errorf("payroll: recovery lines %s: %w", emp.ID, rerr)
			}
			if aerr := s.markAttendanceApplied(ctx, p.TenantID, id, items.AttendanceIDs); aerr != nil {
				return nil, fmt.Errorf("payroll: attendance deductions %s: %w", emp.ID, aerr)
			}
			if perr := s.markPieceOutputsPaid(ctx, p.TenantID, id, items.PieceOutputIDs); perr != nil {
				return nil, fmt.Errorf("payroll: piece output %s: %w", emp.ID, perr)
			}
			if cerr := s.linkClaimsToPayslip(ctx, p.TenantID, id, p.Period, items.ClaimIDs); cerr != nil {
				return nil, fmt.Errorf("payroll: expense claims %s: %w", emp.ID, cerr)
			}
		}
		out = append(out, line)
		if p.OnProgress != nil {
			p.OnProgress(i+1, len(emps))
		}
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
			SetTaxRelief(res.PersonalRelief.Add(res.InsuranceRelief)).
			SetReliefs(res.PersonalRelief.Add(res.InsuranceRelief)).
			SetInsuranceRelief(res.InsuranceRelief).
			SetPensionDeduction(res.PensionDeduction).
			SetMortgageDeduction(res.MortgageDeduction).
			SetDisabilityExemption(res.DisabilityExemption).
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
	// A payslip posted for payment or paid keeps its figures; corrections go through a reversal
	// or the next run.
	if existing.Published || (existing.BatchRef != nil && existing.ApprovalStatus == "approved") {
		return existing.ID, errPayslipLocked
	}

	// New figures need a new approval.
	row, uerr := existing.Update().
		SetApprovalStatus("draft").
		SetPayrollStatus("complete").
		SetGrossPay(res.GrossPay).
		SetTaxablePay(res.TaxablePay).
		SetPaye(res.PAYE).
		SetTaxRelief(res.PersonalRelief.Add(res.InsuranceRelief)).
		SetReliefs(res.PersonalRelief.Add(res.InsuranceRelief)).
		SetInsuranceRelief(res.InsuranceRelief).
		SetPensionDeduction(res.PensionDeduction).
		SetMortgageDeduction(res.MortgageDeduction).
		SetDisabilityExemption(res.DisabilityExemption).
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
