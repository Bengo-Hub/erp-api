package payroll

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/advance"
	"github.com/Bengo-Hub/erp-api/internal/ent/casualpayment"
	"github.com/Bengo-Hub/erp-api/internal/platform/tenantref"
)

// CasualPaymentInput is the unified create/update payload for a casual payment (both a direct
// payout to a casual employee and a reimbursement to a PM who paid an informal worker).
type CasualPaymentInput struct {
	SettlementMode      string // direct_payout | reimburse_engager
	EmployeeID          *uuid.UUID
	WorkerName          string
	WorkerIDNumber      string
	WorkerPhone         string
	EngagedByEmployeeID *uuid.UUID
	ImprestAdvanceID    *uuid.UUID
	WageType            string
	Quantity            decimal.Decimal
	Rate                decimal.Decimal
	TaskDescription     string
	WorkDate            *time.Time
	PaymentDate         *time.Time
	PayrollMonth        *time.Time
	ProjectID           *uuid.UUID
	CostCenterID        *uuid.UUID
	PaymentOption       string
}

// CasualPaymentFilter narrows the casual-payments list.
type CasualPaymentFilter struct {
	PayrollMonth   *time.Time
	ProjectID      *uuid.UUID
	SettlementMode string
	WageType       string
	EmployeeID     *uuid.UUID
}

// normalize computes amount = quantity × rate, defaulting lump_sum quantity to 1.
func (in *CasualPaymentInput) amount() decimal.Decimal {
	q := in.Quantity
	if in.WageType == "lump_sum" && q.IsZero() {
		q = decimal.NewFromInt(1)
	}
	return q.Mul(in.Rate)
}

// ListCasualPayments returns the tenant's casual payments (newest first) with optional filters.
func (s *Service) ListCasualPayments(ctx context.Context, tenantID uuid.UUID, f CasualPaymentFilter, limit, offset int) ([]*ent.CasualPayment, int, error) {
	q := s.orm.CasualPayment.Query().Where(casualpayment.TenantID(tenantID), casualpayment.DeleteStatus(false))
	if f.ProjectID != nil {
		q = q.Where(casualpayment.ProjectID(*f.ProjectID))
	}
	if f.EmployeeID != nil {
		q = q.Where(casualpayment.EmployeeID(*f.EmployeeID))
	}
	if f.SettlementMode != "" {
		q = q.Where(casualpayment.SettlementModeEQ(casualpayment.SettlementMode(f.SettlementMode)))
	}
	if f.WageType != "" {
		q = q.Where(casualpayment.WageTypeEQ(casualpayment.WageType(f.WageType)))
	}
	if f.PayrollMonth != nil {
		start := *f.PayrollMonth
		end := start.AddDate(0, 1, 0)
		q = q.Where(casualpayment.PayrollMonthGTE(start), casualpayment.PayrollMonthLT(end))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, err
	}
	rows, err := q.Order(ent.Desc(casualpayment.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	return rows, total, err
}

// CasualTotalIssued sums the amount of all non-deleted casual payments matching the filter
// (drives the "Total Issued" tile).
func (s *Service) CasualTotalIssued(ctx context.Context, tenantID uuid.UUID, f CasualPaymentFilter) (decimal.Decimal, error) {
	rows, _, err := s.ListCasualPayments(ctx, tenantID, f, 100000, 0)
	if err != nil {
		return decimal.Zero, err
	}
	sum := decimal.Zero
	for _, r := range rows {
		sum = sum.Add(r.Amount)
	}
	return sum, nil
}

// GetCasualPayment fetches one record.
func (s *Service) GetCasualPayment(ctx context.Context, tenantID, id uuid.UUID) (*ent.CasualPayment, error) {
	return s.orm.CasualPayment.Query().
		Where(casualpayment.ID(id), casualpayment.TenantID(tenantID), casualpayment.DeleteStatus(false)).Only(ctx)
}

// checkCasualRefs requires the worker, the engaging employee and the imprest advance to be the
// tenant's own. Projects and cost centres belong to other services and are references only.
func (s *Service) checkCasualRefs(ctx context.Context, tenantID uuid.UUID, in CasualPaymentInput) error {
	if err := tenantref.Employee(ctx, s.orm, tenantID, "employee", in.EmployeeID); err != nil {
		return err
	}
	if err := tenantref.Employee(ctx, s.orm, tenantID, "engaging employee", in.EngagedByEmployeeID); err != nil {
		return err
	}
	if in.ImprestAdvanceID == nil {
		return nil
	}
	return tenantref.Require(ctx, "imprest advance", s.orm.Advance.Query().
		Where(advance.TenantID(tenantID), advance.ID(*in.ImprestAdvanceID)))
}

// CreateCasualPayment creates a casual payment (status=pending), computing amount = quantity × rate.
func (s *Service) CreateCasualPayment(ctx context.Context, tenantID uuid.UUID, in CasualPaymentInput) (*ent.CasualPayment, error) {
	mode := in.SettlementMode
	if mode == "" {
		mode = "direct_payout"
	}
	if mode == "direct_payout" && in.EmployeeID == nil {
		return nil, fmt.Errorf("a casual employee is required for a direct payout")
	}
	if mode == "reimburse_engager" && in.WorkerName == "" {
		return nil, fmt.Errorf("worker_name is required for a reimbursement")
	}
	amount := in.amount()
	if amount.IsZero() {
		return nil, fmt.Errorf("quantity × rate must be greater than zero")
	}
	if err := s.checkCasualRefs(ctx, tenantID, in); err != nil {
		return nil, err
	}
	c := s.orm.CasualPayment.Create().
		SetTenantID(tenantID).
		SetSettlementMode(casualpayment.SettlementMode(mode)).
		SetNillableEmployeeID(in.EmployeeID).
		SetNillableEngagedByEmployeeID(in.EngagedByEmployeeID).
		SetNillableImprestAdvanceID(in.ImprestAdvanceID).
		SetNillableProjectID(in.ProjectID).
		SetNillableCostCenterID(in.CostCenterID).
		SetNillableWorkDate(in.WorkDate).
		SetNillablePaymentDate(in.PaymentDate).
		SetNillablePayrollMonth(in.PayrollMonth).
		SetQuantity(in.Quantity).
		SetRate(in.Rate).
		SetAmount(amount)
	if in.WageType != "" {
		c = c.SetWageType(casualpayment.WageType(in.WageType))
	}
	if in.WorkerName != "" {
		c = c.SetWorkerName(in.WorkerName)
	}
	if in.WorkerIDNumber != "" {
		c = c.SetWorkerIDNumber(in.WorkerIDNumber)
	}
	if in.WorkerPhone != "" {
		c = c.SetWorkerPhone(in.WorkerPhone)
	}
	if in.TaskDescription != "" {
		c = c.SetTaskDescription(in.TaskDescription)
	}
	if in.PaymentOption != "" {
		c = c.SetPaymentOption(in.PaymentOption)
	}
	return c.Save(ctx)
}

// UpdateCasualPayment edits a record (recomputing amount from quantity × rate).
func (s *Service) UpdateCasualPayment(ctx context.Context, tenantID, id uuid.UUID, in CasualPaymentInput) (*ent.CasualPayment, error) {
	existing, err := s.GetCasualPayment(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if err := s.checkCasualRefs(ctx, tenantID, in); err != nil {
		return nil, err
	}
	u := existing.Update().
		SetQuantity(in.Quantity).
		SetRate(in.Rate).
		SetAmount(in.amount())
	if in.WageType != "" {
		u = u.SetWageType(casualpayment.WageType(in.WageType))
	}
	if in.TaskDescription != "" {
		u = u.SetTaskDescription(in.TaskDescription)
	}
	if in.PaymentOption != "" {
		u = u.SetPaymentOption(in.PaymentOption)
	}
	if in.ProjectID != nil {
		u = u.SetProjectID(*in.ProjectID)
	}
	if in.CostCenterID != nil {
		u = u.SetCostCenterID(*in.CostCenterID)
	}
	if in.EmployeeID != nil {
		u = u.SetEmployeeID(*in.EmployeeID)
	}
	if in.PayrollMonth != nil {
		u = u.SetPayrollMonth(*in.PayrollMonth)
	}
	if in.PaymentDate != nil {
		u = u.SetPaymentDate(*in.PaymentDate)
	}
	return u.Save(ctx)
}

// DeleteCasualPayment soft-deletes a record.
func (s *Service) DeleteCasualPayment(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.CasualPayment.Update().
		Where(casualpayment.ID(id), casualpayment.TenantID(tenantID)).
		SetDeleteStatus(true).Save(ctx)
	if err != nil {
		return fmt.Errorf("casual payment: delete: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("casual payment: record not found")
	}
	return nil
}

// ApproveCasualPayment approves a record and emits erp.casual_payment.approved so treasury posts
// the cost to the GL — DR wages (direct_payout) or DR casual-labour (reimburse_engager), CR the
// matching credit — attributed to the project/cost-center. Idempotent.
func (s *Service) ApproveCasualPayment(ctx context.Context, tenantID, id, approverID uuid.UUID) (*ent.CasualPayment, error) {
	existing, err := s.GetCasualPayment(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if existing.Status == casualpayment.StatusApproved || existing.Status == casualpayment.StatusPaid {
		return existing, nil // idempotent
	}
	updated, err := existing.Update().
		SetStatus(casualpayment.StatusApproved).
		SetNillableApproverID(&approverID).
		SetApprovedAt(time.Now()).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("casual payment: approve: %w", err)
	}
	if s.publisher != nil {
		// worker_name: informal worker name (reimburse mode) or the casual employee's name
		// (direct_payout) — treasury labels the GL line with it.
		workerName := updated.WorkerName
		if workerName == "" && updated.EmployeeID != nil {
			if name, _ := s.EmployeeLabel(ctx, tenantID, *updated.EmployeeID); name != "" {
				workerName = name
			}
		}
		projectID := ""
		if updated.ProjectID != nil {
			projectID = updated.ProjectID.String()
		}
		// Inner payload MUST match treasury casualLaborPayload (record_id, tenant_id, worker_name,
		// amount, currency, project_id, cost_center_id). Treasury posts every approved casual
		// payment the same way, DR 6300 Casual Labour and CR 2600 Employee Reimbursements Payable,
		// whatever the settlement mode, and the payable is then settled through accounts payable.
		// settlement_mode, wage_type and employee_id travel with the event so treasury can book a
		// direct payout differently once its subscriber reads them; today it does not.
		payload := map[string]any{
			"record_id":       updated.ID.String(),
			"tenant_id":       tenantID.String(),
			"worker_name":     workerName,
			"amount":          updated.Amount.StringFixed(2),
			"currency":        "KES",
			"project_id":      projectID,
			"settlement_mode": updated.SettlementMode.String(),
			"wage_type":       updated.WageType.String(),
		}
		if updated.EmployeeID != nil {
			payload["employee_id"] = updated.EmployeeID.String()
		}
		if updated.EngagedByEmployeeID != nil {
			payload["engaged_by_employee_id"] = updated.EngagedByEmployeeID.String()
		}
		if updated.CostCenterID != nil {
			payload["cost_center_id"] = updated.CostCenterID.String()
		}
		if err := s.publisher.Publish(ctx, tenantID, updated.ID, "casual_payment.approved", payload); err != nil {
			return updated, fmt.Errorf("casual payment: publish approved: %w", err)
		}
	}
	return updated, nil
}
