// Package approvals implements a generic, tenant-scoped approval-workflow engine reused
// across HR/Ops modules (leave, appraisals, payroll, contracts, ...). It uses a typed
// module enum, tenant-scoped workflows and steps, and approver resolution against the ERP
// Employee/HRDetails model. Supports multi-step chains, approve/reject/escalate, and emits approval
// lifecycle events to the transactional outbox.
package approvals

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalstepaction"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalworkflow"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalworkflowstep"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
)

// Emitter publishes approval lifecycle events to the outbox. Optional (nil disables events).
type Emitter interface {
	EmitApprovalEvent(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest, eventType string) error
}

// Service is the approval engine. Every query is tenant-scoped.
type Service struct {
	orm  *ent.Client
	emit Emitter
}

func NewService(orm *ent.Client, emit Emitter) *Service {
	return &Service{orm: orm, emit: emit}
}

// Decision is the terminal/intermediate outcome reported by Decide.
type Decision struct {
	Request  *ent.ApprovalRequest
	Action   *ent.ApprovalStepAction
	Finished bool // true when the request reached a terminal state (approved/rejected)
}

// SubmitInput requests the creation of an approval workflow instance for an object.
type SubmitInput struct {
	Module              string
	ObjectID            uuid.UUID
	ObjectReference     string
	RequesterEmployeeID *uuid.UUID
	SubmittedBy         *uuid.UUID
}

// Submit creates an ApprovalRequest for an object using the tenant's active workflow for
// the module, materializing per-step pending actions with resolved approvers. If no active
// workflow with steps exists, it returns (nil, nil) so callers can fall back to a direct
// single-approver decision (preserves behaviour for tenants that haven't configured chains).
func (s *Service) Submit(ctx context.Context, tenantID uuid.UUID, in SubmitInput) (*ent.ApprovalRequest, error) {
	wf, err := s.orm.ApprovalWorkflow.Query().
		Where(
			approvalworkflow.TenantID(tenantID),
			approvalworkflow.ModuleEQ(approvalworkflow.Module(in.Module)),
			approvalworkflow.IsActive(true),
		).
		WithSteps(func(q *ent.ApprovalWorkflowStepQuery) {
			q.Order(ent.Asc(approvalworkflowstep.FieldSequence))
		}).
		First(ctx)
	if ent.IsNotFound(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("approvals: load workflow: %w", err)
	}
	if len(wf.Edges.Steps) == 0 {
		return nil, nil
	}

	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	reqBuilder := tx.ApprovalRequest.Create().
		SetTenantID(tenantID).
		SetModule(approvalrequest.Module(in.Module)).
		SetObjectID(in.ObjectID).
		SetObjectReference(in.ObjectReference).
		SetWorkflowID(wf.ID).
		SetStatus(approvalrequest.StatusPending).
		SetCurrentSequence(wf.Edges.Steps[0].Sequence)
	if in.RequesterEmployeeID != nil {
		reqBuilder = reqBuilder.SetRequesterEmployeeID(*in.RequesterEmployeeID)
	}
	if in.SubmittedBy != nil {
		reqBuilder = reqBuilder.SetSubmittedBy(*in.SubmittedBy)
	}
	req, err := reqBuilder.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: create request: %w", err)
	}

	for _, step := range wf.Edges.Steps {
		approver := s.resolveApprover(ctx, tx.Client(), tenantID, step.ApproverType.String(), step.ApproverEmployeeID, in.RequesterEmployeeID)
		ab := tx.ApprovalStepAction.Create().
			SetTenantID(tenantID).
			SetRequestID(req.ID).
			SetSequence(step.Sequence).
			SetName(step.Name).
			SetApproverType(approvalstepaction.ApproverType(step.ApproverType)).
			SetStatus(approvalstepaction.StatusPending)
		if step.ApproverRole != "" {
			ab = ab.SetApproverRole(step.ApproverRole)
		}
		if approver != nil {
			ab = ab.SetApproverEmployeeID(*approver)
		}
		if _, err := ab.Save(ctx); err != nil {
			return nil, fmt.Errorf("approvals: create step action: %w", err)
		}
	}

	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("approvals: commit submit: %w", err)
	}
	s.fireEvent(ctx, tenantID, req, "approval.requested")
	return req, nil
}

// resolveApprover resolves a step's approver employee id by strategy. Best-effort: returns
// nil when it cannot resolve (role/owner steps are decided by RBAC at action time, and
// manager/department_head fall back to nil if the requester has no HRDetails).
func (s *Service) resolveApprover(ctx context.Context, c *ent.Client, tenantID uuid.UUID, approverType string, fixed, requester *uuid.UUID) *uuid.UUID {
	switch approverType {
	case "user":
		return fixed
	case "manager", "department_head":
		if requester == nil {
			return nil
		}
		hr, err := c.HRDetails.Query().
			Where(hrdetails.TenantID(tenantID), hrdetails.EmployeeID(*requester)).
			First(ctx)
		if err != nil {
			return nil
		}
		if approverType == "manager" {
			return hr.ReportsToID
		}
		return hr.HeadOfDepartmentID
	default: // role | owner — resolved by RBAC at action time
		return nil
	}
}

// fireEvent emits an approval lifecycle event (best-effort).
func (s *Service) fireEvent(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest, eventType string) {
	if s.emit == nil || req == nil {
		return
	}
	_ = s.emit.EmitApprovalEvent(ctx, tenantID, req, eventType)
}

// touchDecided sets decided_at on terminal transitions.
func decidedNow() time.Time { return time.Now().UTC() }
