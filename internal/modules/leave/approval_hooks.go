package leave

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
)

// errNotPending marks a decision on a request that is no longer pending.
var errNotPending = errors.New("is not pending")

// SetApprovals wires the approval engine into the leave module (called at startup). Decisions
// made on the generic approvals screen are checked and applied through the engine's guard and
// hook.
func (s *Service) SetApprovals(a Approver) {
	s.approvals = a
	if e, ok := a.(interface {
		RegisterHook(module string, h approvals.Hook)
		RegisterGuard(module string, g approvals.Guard)
	}); ok {
		e.RegisterHook(moduleLeaveRequest, s.applyApprovalDecision)
		e.RegisterGuard(moduleLeaveRequest, s.guardApproval)
	}
}

// guardApproval refuses an approval the leave could not take, before it is recorded.
func (s *Service) guardApproval(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest) error {
	return s.checkApprovable(ctx, tenantID, req.ObjectID)
}

func (s *Service) checkApprovable(ctx context.Context, tenantID, id uuid.UUID) error {
	row, err := s.Get(ctx, tenantID, id)
	if ent.IsNotFound(err) {
		return ErrRequestNotFound
	}
	if err != nil {
		return fmt.Errorf("leave: load request: %w", err)
	}
	if row.Status != "pending" {
		return fmt.Errorf("leave: cannot approve a %s request", row.Status)
	}
	return s.refuseOverBalance(ctx, s.orm, tenantID, row)
}

// applyApprovalDecision applies a finished approval to its leave request. A request that is no
// longer pending is left alone, so a retry changes nothing.
func (s *Service) applyApprovalDecision(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest) error {
	var actor *uuid.UUID
	reason := ""
	full, err := s.approvals.FindRequestForObject(ctx, tenantID, moduleLeaveRequest, req.ObjectID)
	if err == nil && full.ID == req.ID {
		for _, a := range full.Edges.Actions {
			if a.ActedBy != nil {
				actor, reason = a.ActedBy, a.Comment
			}
		}
	}
	switch req.Status {
	case approvalrequest.StatusApproved:
		_, err = s.approve(ctx, tenantID, req.ObjectID, nil, actor)
	case approvalrequest.StatusRejected:
		_, err = s.reject(ctx, tenantID, req.ObjectID, reason, actor)
	default:
		return nil
	}
	if errors.Is(err, errNotPending) {
		return nil
	}
	return err
}
