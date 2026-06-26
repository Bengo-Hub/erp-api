package payroll

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/casuallaborrecord"
)

// CasualLaborInput is the create/update payload for a casual-labour record.
type CasualLaborInput struct {
	EngagedByEmployeeID *uuid.UUID
	ProjectID           *uuid.UUID
	CostCenterID        *uuid.UUID
	WorkerName          string
	WorkerIDNumber      string
	WorkerPhone         string
	TaskDescription     string
	Amount              decimal.Decimal
	PaymentMethod       string
	ImprestAdvanceID    *uuid.UUID
}

// ListCasualLabor returns the tenant's casual-labour records (newest first).
func (s *Service) ListCasualLabor(ctx context.Context, tenantID uuid.UUID, projectID *uuid.UUID, limit, offset int) ([]*ent.CasualLaborRecord, int, error) {
	q := s.orm.CasualLaborRecord.Query().Where(casuallaborrecord.TenantID(tenantID), casuallaborrecord.DeleteStatus(false))
	if projectID != nil {
		q = q.Where(casuallaborrecord.ProjectID(*projectID))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, err
	}
	rows, err := q.Order(ent.Desc(casuallaborrecord.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	return rows, total, err
}

// GetCasualLabor fetches one record.
func (s *Service) GetCasualLabor(ctx context.Context, tenantID, id uuid.UUID) (*ent.CasualLaborRecord, error) {
	return s.orm.CasualLaborRecord.Query().
		Where(casuallaborrecord.ID(id), casuallaborrecord.TenantID(tenantID), casuallaborrecord.DeleteStatus(false)).Only(ctx)
}

// CreateCasualLabor creates a casual-labour record (status=pending).
func (s *Service) CreateCasualLabor(ctx context.Context, tenantID uuid.UUID, in CasualLaborInput) (*ent.CasualLaborRecord, error) {
	if in.WorkerName == "" || in.Amount.IsZero() {
		return nil, fmt.Errorf("worker_name and a non-zero amount are required")
	}
	c := s.orm.CasualLaborRecord.Create().
		SetTenantID(tenantID).
		SetWorkerName(in.WorkerName).
		SetAmount(in.Amount).
		SetNillableEngagedByEmployeeID(in.EngagedByEmployeeID).
		SetNillableProjectID(in.ProjectID).
		SetNillableCostCenterID(in.CostCenterID).
		SetNillableImprestAdvanceID(in.ImprestAdvanceID)
	if in.WorkerIDNumber != "" {
		c = c.SetWorkerIDNumber(in.WorkerIDNumber)
	}
	if in.WorkerPhone != "" {
		c = c.SetWorkerPhone(in.WorkerPhone)
	}
	if in.TaskDescription != "" {
		c = c.SetTaskDescription(in.TaskDescription)
	}
	if in.PaymentMethod != "" {
		c = c.SetPaymentMethod(in.PaymentMethod)
	}
	return c.Save(ctx)
}

// UpdateCasualLabor edits a pending record.
func (s *Service) UpdateCasualLabor(ctx context.Context, tenantID, id uuid.UUID, in CasualLaborInput) (*ent.CasualLaborRecord, error) {
	existing, err := s.GetCasualLabor(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	u := existing.Update()
	if in.WorkerName != "" {
		u = u.SetWorkerName(in.WorkerName)
	}
	if !in.Amount.IsZero() {
		u = u.SetAmount(in.Amount)
	}
	if in.TaskDescription != "" {
		u = u.SetTaskDescription(in.TaskDescription)
	}
	if in.PaymentMethod != "" {
		u = u.SetPaymentMethod(in.PaymentMethod)
	}
	if in.ProjectID != nil {
		u = u.SetProjectID(*in.ProjectID)
	}
	if in.CostCenterID != nil {
		u = u.SetCostCenterID(*in.CostCenterID)
	}
	return u.Save(ctx)
}

// DeleteCasualLabor soft-deletes a record.
func (s *Service) DeleteCasualLabor(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.CasualLaborRecord.Update().
		Where(casuallaborrecord.ID(id), casuallaborrecord.TenantID(tenantID)).
		SetDeleteStatus(true).Save(ctx)
	if err != nil {
		return fmt.Errorf("casual labor: delete: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("casual labor: record not found")
	}
	return nil
}

// ApproveCasualLabor approves a record and emits erp.casual_labor.approved so treasury posts the
// casual-labour cost to the GL (DR casual labour expense / CR employee payable — reimbursed via AP
// to the engager, or settled against their imprest). Idempotent.
func (s *Service) ApproveCasualLabor(ctx context.Context, tenantID, id, approverID uuid.UUID) (*ent.CasualLaborRecord, error) {
	existing, err := s.GetCasualLabor(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if existing.Status == casuallaborrecord.StatusApproved || existing.Status == casuallaborrecord.StatusPaid {
		return existing, nil // already approved — idempotent
	}
	updated, err := existing.Update().
		SetStatus(casuallaborrecord.StatusApproved).
		SetNillableApproverID(&approverID).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("casual labor: approve: %w", err)
	}
	if s.publisher != nil {
		payload := map[string]any{
			"record_id":   updated.ID.String(),
			"tenant_id":   tenantID.String(),
			"worker_name": updated.WorkerName,
			"amount":      updated.Amount.String(),
			"currency":    "KES",
		}
		if updated.ProjectID != nil {
			payload["project_id"] = updated.ProjectID.String()
		}
		if updated.EngagedByEmployeeID != nil {
			payload["engaged_by_employee_id"] = updated.EngagedByEmployeeID.String()
		}
		if err := s.publisher.Publish(ctx, tenantID, updated.ID.String(), "casual_labor.approved", payload); err != nil {
			return updated, fmt.Errorf("casual labor: publish approved: %w", err)
		}
	}
	return updated, nil
}
