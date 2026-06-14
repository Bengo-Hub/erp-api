// Package payroll runs payroll generation (using payrollengine) and persists payslips,
// all tenant-isolated. Recoverable persistence is a separate atomic step from calc.
package payroll

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/advance"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebenefit"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeloan"
	"github.com/Bengo-Hub/erp-api/internal/ent/lossanddamage"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// Service generates and stores payslips.
type Service struct {
	orm      *ent.Client
	settings *payrollsettings.Service
}

func NewService(orm *ent.Client, settings *payrollsettings.Service) *Service {
	return &Service{orm: orm, settings: settings}
}

// RunParams controls a payroll run.
type RunParams struct {
	TenantID        uuid.UUID
	OutletID        uuid.UUID // uuid.Nil = all outlets
	Period          time.Time // first of month
	EmployeeIDs     []uuid.UUID
	RecoverAdvances bool
	CreatedBy       uuid.UUID
	Persist         bool // true = generate (write payslips); false = preview only
}

// LineResult pairs an employee with their engine output.
type LineResult struct {
	EmployeeID uuid.UUID                    `json:"employee_id"`
	Result     payrollengine.PayslipResult  `json:"result"`
	PayslipID  *uuid.UUID                   `json:"payslip_id,omitempty"`
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
		in, ierr := s.buildEmployeeInput(ctx, p, emp)
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
	return q.All(ctx)
}

// buildEmployeeInput loads salary + active, effective-dated recoverables for the employee
// and maps them to the pure engine input (no persistence — gaps §2.7).
func (s *Service) buildEmployeeInput(ctx context.Context, p RunParams, emp *ent.Employee) (payrollengine.EmployeeInput, error) {
	var in payrollengine.EmployeeInput

	sal, err := s.orm.SalaryDetails.Query().
		Where(salarydetails.TenantID(p.TenantID), salarydetails.EmployeeID(emp.ID), salarydetails.IsActive(true)).
		First(ctx)
	if ent.IsNotFound(err) {
		return in, fmt.Errorf("no active salary details")
	}
	if err != nil {
		return in, err
	}
	in.GrossPay = sal.MonthlySalary
	in.TaxCategory = sal.IncomeTax

	// Loans: recover min(installment, outstanding) for active, period-effective loans.
	loans, err := s.orm.EmployeeLoan.Query().
		Where(employeeloan.TenantID(p.TenantID), employeeloan.EmployeeID(emp.ID), employeeloan.IsActive(true)).
		All(ctx)
	if err != nil {
		return in, err
	}
	for _, l := range loans {
		if !dateActive(l.StartDate, l.EndDate, p.Period) {
			continue
		}
		in.Loans = append(in.Loans, payrollengine.Recoverable{
			Installment: l.MonthlyInstallment,
			Outstanding: l.PrincipalAmount.Sub(l.AmountRepaid),
		})
	}

	// Advances.
	advs, err := s.orm.Advance.Query().
		Where(advance.TenantID(p.TenantID), advance.EmployeeID(emp.ID), advance.IsActive(true)).
		All(ctx)
	if err != nil {
		return in, err
	}
	for _, a := range advs {
		if a.IssueDate != nil && a.IssueDate.After(p.Period) {
			continue
		}
		install, e := s.installmentFor(ctx, a.RepayOptionID)
		if e != nil {
			return in, e
		}
		in.Advances = append(in.Advances, payrollengine.Recoverable{
			Installment: install,
			Outstanding: a.AmountIssued.Sub(a.AmountRepaid),
		})
	}

	// Loss/damages.
	lds, err := s.orm.LossAndDamage.Query().
		Where(lossanddamage.TenantID(p.TenantID), lossanddamage.EmployeeID(emp.ID), lossanddamage.IsActive(true)).
		All(ctx)
	if err != nil {
		return in, err
	}
	for _, ld := range lds {
		if ld.IssueDate != nil && ld.IssueDate.After(p.Period) {
			continue
		}
		install, e := s.installmentFor(ctx, ld.RepayOptionID)
		if e != nil {
			return in, e
		}
		in.LossDamages = append(in.LossDamages, payrollengine.Recoverable{
			Installment: install,
			Outstanding: ld.DamageAmount.Sub(ld.AmountRepaid),
		})
	}

	// Non-cash benefits.
	bens, err := s.orm.EmployeeBenefit.Query().
		Where(employeebenefit.TenantID(p.TenantID), employeebenefit.EmployeeID(emp.ID), employeebenefit.IsActive(true), employeebenefit.NonCash(true)).
		All(ctx)
	if err != nil {
		return in, err
	}
	total := decimal.Zero
	for _, b := range bens {
		if !dateActive(b.EffectiveDate, b.EndDate, p.Period) {
			continue
		}
		total = total.Add(b.Amount)
	}
	in.NonCashBenefits = total
	return in, nil
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
