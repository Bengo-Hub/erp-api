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
	// NoOfInstallments drives the RepayOption installment plan (installment_amount = amount/n).
	// 0 or 1 means a single lump-sum recovery (no plan created).
	NoOfInstallments int
	// RepayOptionID is the existing plan id on update (so editing the installment count reuses
	// the row instead of orphaning it). Nil on create.
	RepayOptionID *uuid.UUID
}

// GetEmployee returns a tenant-scoped employee (identity fields for payslip docs / the
// self-or-manager download check). Returns an ent NotFound error when absent.
func (s *Service) GetEmployee(ctx context.Context, tenantID, employeeID uuid.UUID) (*ent.Employee, error) {
	return s.orm.Employee.Query().
		Where(employee.ID(employeeID), employee.TenantID(tenantID)).Only(ctx)
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

func (s *Service) ListAdvances(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, status string, limit, offset int) ([]*ent.Advance, int, error) {
	q := s.orm.Advance.Query().Where(advance.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(advance.EmployeeID(*employeeID))
	}
	switch status {
	case "scheduled":
		q = q.Where(advance.Approved(true), advance.IsActive(true))
	case "approved":
		q = q.Where(advance.Approved(true))
	case "pending":
		q = q.Where(advance.Approved(false), advance.IsActive(true))
	case "disapproved":
		q = q.Where(advance.Approved(false), advance.IsActive(false))
	case "nulled":
		q = q.Where(advance.IsActive(false))
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
	repayID, err := s.ensureRepayOption(ctx, tenantID, nil, in.Amount, in.NoOfInstallments)
	if err != nil {
		return nil, err
	}
	b := s.orm.Advance.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetAmountIssued(in.Amount).
		SetIsActive(in.IsActive).
		SetNillableRepayOptionID(repayID)
	if in.IssueDate != nil {
		b = b.SetIssueDate(*in.IssueDate)
	}
	if in.Description != "" {
		b = b.SetMetadata(map[string]any{"reason": in.Description})
	}
	return b.Save(ctx)
}

func (s *Service) UpdateAdvance(ctx context.Context, tenantID, id uuid.UUID, in RecoverableInput) (*ent.Advance, error) {
	existing, err := s.orm.Advance.Query().Where(advance.ID(id), advance.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	amount := in.Amount
	if amount.IsZero() {
		amount = existing.AmountIssued
	}
	repayID, err := s.ensureRepayOption(ctx, tenantID, existing.RepayOptionID, amount, in.NoOfInstallments)
	if err != nil {
		return nil, err
	}
	u := existing.Update().SetIsActive(in.IsActive).SetNillableRepayOptionID(repayID)
	if !in.Amount.IsZero() {
		u = u.SetAmountIssued(in.Amount)
	}
	if in.IssueDate != nil {
		u = u.SetIssueDate(*in.IssueDate)
	}
	if in.Description != "" {
		meta := map[string]any{}
		for k, v := range existing.Metadata {
			meta[k] = v
		}
		meta["reason"] = in.Description
		u = u.SetMetadata(meta)
	}
	return u.Save(ctx)
}

// SetAdvanceApproval flips the approved + is_active flags driving the status tabs:
//
//	approve    -> approved=true,  is_active=true  (Scheduled for recovery)
//	disapprove -> approved=false, is_active=false (Disapproved)
//	null       -> approved=false, is_active=false (Nulled / withdrawn)
func (s *Service) SetAdvanceApproval(ctx context.Context, tenantID, id uuid.UUID, approverID uuid.UUID, approve bool) (*ent.Advance, error) {
	existing, err := s.orm.Advance.Query().Where(advance.ID(id), advance.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := existing.Update().SetApproved(approve).SetIsActive(approve)
	if approve {
		u = u.SetNillableApproverID(&approverID)
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

func (s *Service) ListLossDamages(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, status string, limit, offset int) ([]*ent.LossAndDamage, int, error) {
	q := s.orm.LossAndDamage.Query().Where(lossanddamage.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(lossanddamage.EmployeeID(*employeeID))
	}
	switch status {
	case "scheduled":
		q = q.Where(lossanddamage.Approved(true), lossanddamage.IsActive(true))
	case "approved":
		q = q.Where(lossanddamage.Approved(true))
	case "pending":
		q = q.Where(lossanddamage.Approved(false), lossanddamage.IsActive(true))
	case "disapproved":
		q = q.Where(lossanddamage.Approved(false), lossanddamage.IsActive(false))
	case "nulled":
		q = q.Where(lossanddamage.IsActive(false))
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
	repayID, err := s.ensureRepayOption(ctx, tenantID, nil, in.Amount, in.NoOfInstallments)
	if err != nil {
		return nil, err
	}
	b := s.orm.LossAndDamage.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetDamageAmount(in.Amount).
		SetIsActive(in.IsActive).
		SetNillableRepayOptionID(repayID)
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
	amount := in.Amount
	if amount.IsZero() {
		amount = existing.DamageAmount
	}
	repayID, err := s.ensureRepayOption(ctx, tenantID, existing.RepayOptionID, amount, in.NoOfInstallments)
	if err != nil {
		return nil, err
	}
	u := existing.Update().SetIsActive(in.IsActive).SetNillableRepayOptionID(repayID)
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

// SetLossDamageApproval mirrors SetAdvanceApproval for the loss/damage status tabs.
func (s *Service) SetLossDamageApproval(ctx context.Context, tenantID, id uuid.UUID, approverID uuid.UUID, approve bool) (*ent.LossAndDamage, error) {
	existing, err := s.orm.LossAndDamage.Query().Where(lossanddamage.ID(id), lossanddamage.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := existing.Update().SetApproved(approve).SetIsActive(approve)
	if approve {
		u = u.SetNillableApproverID(&approverID)
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
	// Analytic + tax linkage (additive). ClaimType drives tax treatment; Taxable marks the
	// (portion treated as) taxable income. ProjectID/CostCenterID tag the cost for treasury.
	ProjectID    *uuid.UUID
	CostCenterID *uuid.UUID
	ClaimType    string
	Taxable      *bool
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
		SetAmount(in.Amount).
		SetNillableProjectID(in.ProjectID).
		SetNillableCostCenterID(in.CostCenterID)
	if in.Category != "" {
		b = b.SetCategory(in.Category)
	}
	if in.ClaimType != "" {
		b = b.SetClaimType(in.ClaimType)
	}
	if in.Taxable != nil {
		b = b.SetTaxable(*in.Taxable)
	}
	if in.ApplicationDate != nil {
		b = b.SetApplicationDate(*in.ApplicationDate)
	}
	c, err := b.Save(ctx)
	if err != nil {
		return nil, err
	}
	s.publishClaimBestEffort(ctx, tenantID, c.ID, "expense_claim.created", claimPayload(c))
	return c, nil
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
	if in.ClaimType != "" {
		u = u.SetClaimType(in.ClaimType)
	}
	if in.Taxable != nil {
		u = u.SetTaxable(*in.Taxable)
	}
	if in.ProjectID != nil {
		u = u.SetProjectID(*in.ProjectID)
	}
	if in.CostCenterID != nil {
		u = u.SetCostCenterID(*in.CostCenterID)
	}
	if in.ApplicationDate != nil {
		u = u.SetApplicationDate(*in.ApplicationDate)
	}
	c, err := u.Save(ctx)
	if err != nil {
		return nil, err
	}
	if !c.Approved { // an approved claim is already booked; only pending ones are commitments
		s.publishClaimBestEffort(ctx, tenantID, c.ID, "expense_claim.updated", claimPayload(c))
	}
	return c, nil
}

// ApproveClaim approves an expense claim and emits erp.expense_claim.approved so treasury posts
// the reimbursement to the GL. The NON-taxable amount is paid via treasury AP (employee payable),
// NOT through payroll gross — so it never inflates PAYE; the taxable portion (when taxable=true)
// is handled through the payslip taxable lane. Idempotent: re-approving an already-approved claim
// does not re-emit.
//
// With a budget checker wired, the claim is checked against treasury budgets first: a budget set
// to Stop returns *OverBudgetError (nothing changes) unless overrideBudget is set; the caller
// decides who may override.
func (s *Service) ApproveClaim(ctx context.Context, tenantID, id, approverID uuid.UUID, overrideBudget bool) (*ent.ExpenseClaim, error) {
	existing, err := s.GetClaim(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if existing.Approved {
		return existing, nil // already approved — idempotent, no re-emit
	}
	if s.budgets != nil && !overrideBudget {
		if res := s.budgets.CheckClaimBudget(ctx, tenantID, claimCheckOf(existing)); res.Action == "stop" {
			return nil, &OverBudgetError{Result: res}
		}
	}
	updated, err := existing.Update().
		SetApproved(true).
		SetNillableApproverID(&approverID).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("payroll: approve claim: %w", err)
	}
	if s.publisher != nil {
		// The payload MUST match treasury claimApprovedPayload. taxable=true makes treasury skip
		// AP (the taxable portion is taxed via the payslip lane instead).
		if err := s.publisher.Publish(ctx, tenantID, updated.ID, "expense_claim.approved", claimPayload(updated)); err != nil {
			// Approval persisted; event failure is logged by the caller. Surface so caller can retry.
			return updated, fmt.Errorf("payroll: publish expense_claim.approved: %w", err)
		}
	}
	return updated, nil
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
	s.publishClaimBestEffort(ctx, tenantID, id, "expense_claim.deleted", map[string]any{"claim_id": id.String(), "tenant_id": tenantID.String()})
	return nil
}
