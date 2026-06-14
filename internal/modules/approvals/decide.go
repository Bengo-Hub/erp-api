package approvals

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalstepaction"
)

// DecisionInput captures an actor's decision on the current step of a request.
type DecisionInput struct {
	RequestID uuid.UUID
	Approve   bool // true = approve current step; false = reject the whole request
	Escalate  bool // true = mark current step escalated and advance without approving the request
	Comment   string
	ActedBy   *uuid.UUID
}

// Decide records a decision on the current pending step and advances the workflow.
//   - approve: marks the current step approved; if it was the last step the request is
//     approved, otherwise current_sequence advances to the next step.
//   - reject: marks the step rejected and the whole request rejected (terminal).
//   - escalate: marks the step escalated and advances to the next step (or approves if last).
//
// All transitions are atomic and tenant-scoped. Returns the updated request + action and a
// Finished flag the caller uses to apply the domain side-effect (e.g. deduct leave balance).
func (s *Service) Decide(ctx context.Context, tenantID uuid.UUID, in DecisionInput) (*Decision, error) {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	req, err := tx.ApprovalRequest.Query().
		Where(approvalrequest.TenantID(tenantID), approvalrequest.ID(in.RequestID)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: load request: %w", err)
	}
	if req.Status != approvalrequest.StatusPending {
		return nil, fmt.Errorf("approvals: request is already %s", req.Status)
	}

	action, err := tx.ApprovalStepAction.Query().
		Where(
			approvalstepaction.TenantID(tenantID),
			approvalstepaction.RequestID(req.ID),
			approvalstepaction.Sequence(req.CurrentSequence),
		).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: load current step: %w", err)
	}

	actBuilder := action.Update().SetActedAt(decidedNow())
	if in.ActedBy != nil {
		actBuilder = actBuilder.SetActedBy(*in.ActedBy)
	}
	if in.Comment != "" {
		actBuilder = actBuilder.SetComment(in.Comment)
	}

	finished := false
	switch {
	case !in.Approve && !in.Escalate: // reject -> terminal
		if _, err := actBuilder.SetStatus(approvalstepaction.StatusRejected).Save(ctx); err != nil {
			return nil, fmt.Errorf("approvals: reject step: %w", err)
		}
		req, err = req.Update().SetStatus(approvalrequest.StatusRejected).SetDecidedAt(decidedNow()).Save(ctx)
		if err != nil {
			return nil, fmt.Errorf("approvals: reject request: %w", err)
		}
		finished = true
	default: // approve or escalate -> advance
		st := approvalstepaction.StatusApproved
		if in.Escalate {
			st = approvalstepaction.StatusEscalated
		}
		if _, err := actBuilder.SetStatus(st).Save(ctx); err != nil {
			return nil, fmt.Errorf("approvals: advance step: %w", err)
		}
		next, hasNext, nerr := nextSequence(ctx, tx, tenantID, req.ID, req.CurrentSequence)
		if nerr != nil {
			return nil, nerr
		}
		if hasNext {
			req, err = req.Update().SetCurrentSequence(next).Save(ctx)
		} else {
			req, err = req.Update().SetStatus(approvalrequest.StatusApproved).SetDecidedAt(decidedNow()).Save(ctx)
			finished = true
		}
		if err != nil {
			return nil, fmt.Errorf("approvals: update request: %w", err)
		}
	}

	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("approvals: commit decision: %w", err)
	}

	switch {
	case req.Status == approvalrequest.StatusRejected:
		s.fireEvent(ctx, tenantID, req, "approval.rejected")
	case req.Status == approvalrequest.StatusApproved:
		s.fireEvent(ctx, tenantID, req, "approval.approved")
	default:
		s.fireEvent(ctx, tenantID, req, "approval.step_approved")
	}
	return &Decision{Request: req, Action: action, Finished: finished}, nil
}

// nextSequence returns the next pending step's sequence after the current one.
func nextSequence(ctx context.Context, tx *ent.Tx, tenantID, requestID uuid.UUID, current int) (int, bool, error) {
	next, err := tx.ApprovalStepAction.Query().
		Where(
			approvalstepaction.TenantID(tenantID),
			approvalstepaction.RequestID(requestID),
			approvalstepaction.SequenceGT(current),
			approvalstepaction.StatusEQ(approvalstepaction.StatusPending),
		).
		Order(ent.Asc(approvalstepaction.FieldSequence)).
		First(ctx)
	if ent.IsNotFound(err) {
		return 0, false, nil
	}
	if err != nil {
		return 0, false, fmt.Errorf("approvals: lookup next step: %w", err)
	}
	return next.Sequence, true, nil
}

// Cancel marks a pending request cancelled (e.g. the underlying object was withdrawn).
func (s *Service) Cancel(ctx context.Context, tenantID, requestID uuid.UUID) (*ent.ApprovalRequest, error) {
	n, err := s.orm.ApprovalRequest.Update().
		Where(
			approvalrequest.TenantID(tenantID),
			approvalrequest.ID(requestID),
			approvalrequest.StatusEQ(approvalrequest.StatusPending),
		).
		SetStatus(approvalrequest.StatusCancelled).
		SetDecidedAt(decidedNow()).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: cancel: %w", err)
	}
	if n == 0 {
		return nil, fmt.Errorf("approvals: no pending request to cancel")
	}
	req, err := s.orm.ApprovalRequest.Query().
		Where(approvalrequest.TenantID(tenantID), approvalrequest.ID(requestID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	s.fireEvent(ctx, tenantID, req, "approval.cancelled")
	return req, nil
}
