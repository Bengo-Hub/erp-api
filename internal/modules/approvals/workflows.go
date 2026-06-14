package approvals

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalstepaction"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalworkflow"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalworkflowstep"
)

// ---- Workflows ----

// ListWorkflows returns tenant-scoped workflows (optionally filtered by module).
func (s *Service) ListWorkflows(ctx context.Context, tenantID uuid.UUID, module string) ([]*ent.ApprovalWorkflow, error) {
	q := s.orm.ApprovalWorkflow.Query().Where(approvalworkflow.TenantID(tenantID))
	if module != "" {
		q = q.Where(approvalworkflow.ModuleEQ(approvalworkflow.Module(module)))
	}
	return q.WithSteps(func(sq *ent.ApprovalWorkflowStepQuery) {
		sq.Order(ent.Asc(approvalworkflowstep.FieldSequence))
	}).Order(ent.Desc(approvalworkflow.FieldCreatedAt)).All(ctx)
}

// StepInput defines one step of a workflow.
type StepInput struct {
	Sequence           int
	Name               string
	ApproverType       string
	ApproverRole       string
	ApproverEmployeeID *uuid.UUID
	IsOptional         bool
}

// WorkflowInput is the create payload for a workflow + its steps.
type WorkflowInput struct {
	Module      string
	Name        string
	Description string
	IsActive    bool
	Steps       []StepInput
}

// CreateWorkflow inserts a tenant-scoped workflow and its ordered steps atomically.
func (s *Service) CreateWorkflow(ctx context.Context, tenantID uuid.UUID, in WorkflowInput) (*ent.ApprovalWorkflow, error) {
	if len(in.Steps) == 0 {
		return nil, fmt.Errorf("approvals: workflow needs at least one step")
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	wf, err := tx.ApprovalWorkflow.Create().
		SetTenantID(tenantID).
		SetModule(approvalworkflow.Module(in.Module)).
		SetName(in.Name).
		SetDescription(in.Description).
		SetIsActive(in.IsActive).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: create workflow: %w", err)
	}
	for _, st := range in.Steps {
		b := tx.ApprovalWorkflowStep.Create().
			SetTenantID(tenantID).
			SetWorkflowID(wf.ID).
			SetSequence(st.Sequence).
			SetName(st.Name).
			SetApproverType(approvalworkflowstep.ApproverType(st.ApproverType)).
			SetIsOptional(st.IsOptional)
		if st.ApproverRole != "" {
			b = b.SetApproverRole(st.ApproverRole)
		}
		if st.ApproverEmployeeID != nil {
			b = b.SetApproverEmployeeID(*st.ApproverEmployeeID)
		}
		if _, err := b.Save(ctx); err != nil {
			return nil, fmt.Errorf("approvals: create step: %w", err)
		}
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("approvals: commit workflow: %w", err)
	}
	return s.GetWorkflow(ctx, tenantID, wf.ID)
}

// GetWorkflow loads one tenant-scoped workflow with its steps.
func (s *Service) GetWorkflow(ctx context.Context, tenantID, id uuid.UUID) (*ent.ApprovalWorkflow, error) {
	return s.orm.ApprovalWorkflow.Query().
		Where(approvalworkflow.TenantID(tenantID), approvalworkflow.ID(id)).
		WithSteps(func(sq *ent.ApprovalWorkflowStepQuery) {
			sq.Order(ent.Asc(approvalworkflowstep.FieldSequence))
		}).Only(ctx)
}

// SetWorkflowActive toggles a workflow's active flag.
func (s *Service) SetWorkflowActive(ctx context.Context, tenantID, id uuid.UUID, active bool) (*ent.ApprovalWorkflow, error) {
	n, err := s.orm.ApprovalWorkflow.Update().
		Where(approvalworkflow.TenantID(tenantID), approvalworkflow.ID(id)).
		SetIsActive(active).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: update workflow: %w", err)
	}
	if n == 0 {
		return nil, fmt.Errorf("approvals: workflow not found")
	}
	return s.GetWorkflow(ctx, tenantID, id)
}

// DeleteWorkflow removes a workflow and its steps (steps cascade via the edge).
func (s *Service) DeleteWorkflow(ctx context.Context, tenantID, id uuid.UUID) error {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return fmt.Errorf("approvals: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.ApprovalWorkflowStep.Delete().
		Where(approvalworkflowstep.TenantID(tenantID), approvalworkflowstep.WorkflowID(id)).Exec(ctx); err != nil {
		return fmt.Errorf("approvals: delete steps: %w", err)
	}
	n, err := tx.ApprovalWorkflow.Delete().
		Where(approvalworkflow.TenantID(tenantID), approvalworkflow.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("approvals: delete workflow: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("approvals: workflow not found")
	}
	return tx.Commit()
}

// ---- Requests ----

// ListRequests returns approval requests filtered by tenant (+ optional module/status).
func (s *Service) ListRequests(ctx context.Context, tenantID uuid.UUID, module, status string) ([]*ent.ApprovalRequest, error) {
	q := s.orm.ApprovalRequest.Query().Where(approvalrequest.TenantID(tenantID))
	if module != "" {
		q = q.Where(approvalrequest.ModuleEQ(approvalrequest.Module(module)))
	}
	if status != "" {
		q = q.Where(approvalrequest.StatusEQ(approvalrequest.Status(status)))
	}
	return q.WithActions(func(aq *ent.ApprovalStepActionQuery) {
		aq.Order(ent.Asc(approvalstepaction.FieldSequence))
	}).Order(ent.Desc(approvalrequest.FieldCreatedAt)).All(ctx)
}

// GetRequest loads one tenant-scoped request with its step actions.
func (s *Service) GetRequest(ctx context.Context, tenantID, id uuid.UUID) (*ent.ApprovalRequest, error) {
	return s.orm.ApprovalRequest.Query().
		Where(approvalrequest.TenantID(tenantID), approvalrequest.ID(id)).
		WithActions(func(aq *ent.ApprovalStepActionQuery) {
			aq.Order(ent.Asc(approvalstepaction.FieldSequence))
		}).Only(ctx)
}

// FindRequestForObject returns the latest approval request for a given (module, object).
func (s *Service) FindRequestForObject(ctx context.Context, tenantID uuid.UUID, module string, objectID uuid.UUID) (*ent.ApprovalRequest, error) {
	return s.orm.ApprovalRequest.Query().
		Where(
			approvalrequest.TenantID(tenantID),
			approvalrequest.ModuleEQ(approvalrequest.Module(module)),
			approvalrequest.ObjectID(objectID),
		).
		WithActions(func(aq *ent.ApprovalStepActionQuery) {
			aq.Order(ent.Asc(approvalstepaction.FieldSequence))
		}).
		Order(ent.Desc(approvalrequest.FieldCreatedAt)).First(ctx)
}
