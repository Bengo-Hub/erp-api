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
	"github.com/Bengo-Hub/erp-api/internal/ent/expenseclaim"
	"github.com/Bengo-Hub/erp-api/internal/ent/lossanddamage"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
)

// This file adds the read/CRUD surface the erp-ui payroll screens need on top of
// the run/disburse engine: payslip listing/detail, plus advances, loss-damages and
// expense claims management. All queries are tenant-isolated.

// ---- Payslips ----

// ListPayslips returns tenant-scoped payslips (optionally filtered by period/employee),
// newest period first.
func (s *Service) ListPayslips(ctx context.Context, tenantID uuid.UUID, period *time.Time, employeeID *uuid.UUID, limit, offset int) ([]*ent.Payslip, int, error) {
	q := s.orm.Payslip.Query().Where(payslip.TenantID(tenantID), payslip.DeleteStatus(false))
	if period != nil {
		q = q.Where(payslip.PaymentPeriod(*period))
	}
	if employeeID != nil {
		q = q.Where(payslip.EmployeeID(*employeeID))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("payroll: count payslips: %w", err)
	}
	if limit <= 0 || limit > 500 {
		limit = 50
	}
	rows, err := q.Order(ent.Desc(payslip.FieldPaymentPeriod), ent.Desc(payslip.FieldCreatedAt)).
		Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("payroll: list payslips: %w", err)
	}
	return rows, total, nil
}

func (s *Service) GetPayslip(ctx context.Context, tenantID, id uuid.UUID) (*ent.Payslip, error) {
	return s.orm.Payslip.Query().
		Where(payslip.ID(id), payslip.TenantID(tenantID), payslip.DeleteStatus(false)).
		Only(ctx)
}

// SoftDeletePayslip marks a payslip deleted (tenant-scoped).
func (s *Service) SoftDeletePayslip(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.Payslip.Update().
		Where(payslip.ID(id), payslip.TenantID(tenantID)).
		SetDeleteStatus(true).Save(ctx)
	if err != nil {
		return fmt.Errorf("payroll: delete payslip: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("payroll: payslip not found")
	}
	return nil
}

// EmployeeLabel resolves "First Last" + employee_number (best-effort).
func (s *Service) EmployeeLabel(ctx context.Context, tenantID, employeeID uuid.UUID) (name, number string) {
	emp, err := s.orm.Employee.Query().
		Where(employee.ID(employeeID), employee.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return "", ""
	}
	name = emp.FirstName
	if emp.LastName != "" {
		if name != "" {
			name += " "
		}
		name += emp.LastName
	}
	if emp.EmployeeNumber != nil {
		number = *emp.EmployeeNumber
	}
	return name, number
}

// ---- Advances ----

// RecoverableInput is the create payload shared by advances and loss-damages.
type RecoverableInput struct {
	EmployeeID  uuid.UUID
	Amount      decimal.Decimal
	Description string
	IssueDate   *time.Time
	IsActive    bool
}

func (s *Service) employeeBelongs(ctx context.Context, tenantID, employeeID uuid.UUID) error {
	ok, err := s.orm.Employee.Query().Where(employee.ID(employeeID), employee.TenantID(tenantID)).Exist(ctx)
	if err != nil {
		return fmt.Errorf("payroll: employee check: %w", err)
	}
	if !ok {
		return fmt.Errorf("payroll: employee not found for tenant")
	}
	return nil
}

func (s *Service) ListAdvances(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, limit, offset int) ([]*ent.Advance, int, error) {
	q := s.orm.Advance.Query().Where(advance.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(advance.EmployeeID(*employeeID))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("payroll: count advances: %w", err)
	}
	if limit <= 0 || limit > 500 {
		limit = 50
	}
	rows, err := q.Order(ent.Desc(advance.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("payroll: list advances: %w", err)
	}
	return rows, total, nil
}

func (s *Service) CreateAdvance(ctx context.Context, tenantID uuid.UUID, in RecoverableInput) (*ent.Advance, error) {
	if err := s.employeeBelongs(ctx, tenantID, in.EmployeeID); err != nil {
		return nil, err
	}
	b := s.orm.Advance.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetAmountIssued(in.Amount).
		SetIsActive(in.IsActive)
	if in.IssueDate != nil {
		b = b.SetIssueDate(*in.IssueDate)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateAdvance(ctx context.Context, tenantID, id uuid.UUID, in RecoverableInput) (*ent.Advance, error) {
	existing, err := s.orm.Advance.Query().Where(advance.ID(id), advance.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := existing.Update().SetIsActive(in.IsActive)
	if !in.Amount.IsZero() {
		u = u.SetAmountIssued(in.Amount)
	}
	if in.IssueDate != nil {
		u = u.SetIssueDate(*in.IssueDate)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteAdvance(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.Advance.Delete().Where(advance.ID(id), advance.TenantID(tenantID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("payroll: delete advance: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("payroll: advance not found")
	}
	return nil
}

// ---- Loss & damages ----

func (s *Service) ListLossDamages(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, limit, offset int) ([]*ent.LossAndDamage, int, error) {
	q := s.orm.LossAndDamage.Query().Where(lossanddamage.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(lossanddamage.EmployeeID(*employeeID))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("payroll: count loss-damages: %w", err)
	}
	if limit <= 0 || limit > 500 {
		limit = 50
	}
	rows, err := q.Order(ent.Desc(lossanddamage.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("payroll: list loss-damages: %w", err)
	}
	return rows, total, nil
}

func (s *Service) CreateLossDamage(ctx context.Context, tenantID uuid.UUID, in RecoverableInput) (*ent.LossAndDamage, error) {
	if err := s.employeeBelongs(ctx, tenantID, in.EmployeeID); err != nil {
		return nil, err
	}
	b := s.orm.LossAndDamage.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetDamageAmount(in.Amount).
		SetIsActive(in.IsActive)
	if in.Description != "" {
		b = b.SetDescription(in.Description)
	}
	if in.IssueDate != nil {
		b = b.SetIssueDate(*in.IssueDate)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateLossDamage(ctx context.Context, tenantID, id uuid.UUID, in RecoverableInput) (*ent.LossAndDamage, error) {
	existing, err := s.orm.LossAndDamage.Query().Where(lossanddamage.ID(id), lossanddamage.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := existing.Update().SetIsActive(in.IsActive)
	if !in.Amount.IsZero() {
		u = u.SetDamageAmount(in.Amount)
	}
	if in.Description != "" {
		u = u.SetDescription(in.Description)
	}
	if in.IssueDate != nil {
		u = u.SetIssueDate(*in.IssueDate)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteLossDamage(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.LossAndDamage.Delete().Where(lossanddamage.ID(id), lossanddamage.TenantID(tenantID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("payroll: delete loss-damage: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("payroll: loss-damage not found")
	}
	return nil
}

// ---- Expense claims ----

// ClaimInput is the create/update payload for an expense claim.
type ClaimInput struct {
	EmployeeID      uuid.UUID
	Amount          decimal.Decimal
	Category        string
	ApplicationDate *time.Time
}

func (s *Service) ListClaims(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, limit, offset int) ([]*ent.ExpenseClaim, int, error) {
	q := s.orm.ExpenseClaim.Query().Where(expenseclaim.TenantID(tenantID), expenseclaim.DeleteStatus(false))
	if employeeID != nil {
		q = q.Where(expenseclaim.EmployeeID(*employeeID))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("payroll: count claims: %w", err)
	}
	if limit <= 0 || limit > 500 {
		limit = 50
	}
	rows, err := q.Order(ent.Desc(expenseclaim.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("payroll: list claims: %w", err)
	}
	return rows, total, nil
}

func (s *Service) GetClaim(ctx context.Context, tenantID, id uuid.UUID) (*ent.ExpenseClaim, error) {
	return s.orm.ExpenseClaim.Query().
		Where(expenseclaim.ID(id), expenseclaim.TenantID(tenantID), expenseclaim.DeleteStatus(false)).
		Only(ctx)
}

func (s *Service) CreateClaim(ctx context.Context, tenantID uuid.UUID, in ClaimInput) (*ent.ExpenseClaim, error) {
	if err := s.employeeBelongs(ctx, tenantID, in.EmployeeID); err != nil {
		return nil, err
	}
	b := s.orm.ExpenseClaim.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetAmount(in.Amount)
	if in.Category != "" {
		b = b.SetCategory(in.Category)
	}
	if in.ApplicationDate != nil {
		b = b.SetApplicationDate(*in.ApplicationDate)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateClaim(ctx context.Context, tenantID, id uuid.UUID, in ClaimInput) (*ent.ExpenseClaim, error) {
	existing, err := s.GetClaim(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	u := existing.Update()
	if !in.Amount.IsZero() {
		u = u.SetAmount(in.Amount)
	}
	if in.Category != "" {
		u = u.SetCategory(in.Category)
	}
	if in.ApplicationDate != nil {
		u = u.SetApplicationDate(*in.ApplicationDate)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteClaim(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.ExpenseClaim.Update().
		Where(expenseclaim.ID(id), expenseclaim.TenantID(tenantID)).
		SetDeleteStatus(true).Save(ctx)
	if err != nil {
		return fmt.Errorf("payroll: delete claim: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("payroll: claim not found")
	}
	return nil
}
