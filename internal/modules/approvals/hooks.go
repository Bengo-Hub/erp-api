package approvals

import (
	"context"
	"fmt"
	"sync"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalstepaction"
)

// Hook applies a module's domain change when one of its requests reaches approved or
// rejected through the generic /approvals decide routes. It runs after the decision is
// committed, so it must be idempotent: a retry of a failed apply calls it again.
type Hook func(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest) error

type hookRegistry struct {
	mu sync.RWMutex
	m  map[string]Hook
}

// RegisterHook sets the apply function for a module (one per module; the last one wins).
func (s *Service) RegisterHook(module string, h Hook) {
	s.hooks.mu.Lock()
	defer s.hooks.mu.Unlock()
	if s.hooks.m == nil {
		s.hooks.m = map[string]Hook{}
	}
	s.hooks.m[module] = h
}

// runHook calls the module's hook for a finished request, if one is registered.
func (s *Service) runHook(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest) error {
	s.hooks.mu.RLock()
	h := s.hooks.m[string(req.Module)]
	s.hooks.mu.RUnlock()
	if h == nil {
		return nil
	}
	if err := h(ctx, tenantID, req); err != nil {
		return fmt.Errorf("approvals: apply %s decision: %w", req.Module, err)
	}
	return nil
}

// DecideAndApply is Decide followed by the module hook when the request finished. A hook
// failure is reported in ApplyErr; the decision itself stays recorded.
func (s *Service) DecideAndApply(ctx context.Context, tenantID uuid.UUID, in DecisionInput) (*Decision, error) {
	dec, err := s.Decide(ctx, tenantID, in)
	if err != nil || !dec.Finished {
		return dec, err
	}
	dec.ApplyErr = s.runHook(ctx, tenantID, dec.Request)
	return dec, nil
}

// SubmitWithFallback is Submit, except that a tenant with no active workflow for the module
// still gets a request: one step decided by any holder of fallbackRole. Modules whose
// decisions only happen through the approvals engine use it, so a request is never stuck.
func (s *Service) SubmitWithFallback(ctx context.Context, tenantID uuid.UUID, in SubmitInput, fallbackRole string) (*ent.ApprovalRequest, error) {
	req, err := s.Submit(ctx, tenantID, in)
	if err != nil || req != nil {
		return req, err
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	req, err = tx.ApprovalRequest.Create().
		SetTenantID(tenantID).
		SetModule(approvalrequest.Module(in.Module)).
		SetObjectID(in.ObjectID).
		SetObjectReference(in.ObjectReference).
		SetStatus(approvalrequest.StatusPending).
		SetCurrentSequence(1).
		SetNillableRequesterEmployeeID(in.RequesterEmployeeID).
		SetNillableSubmittedBy(in.SubmittedBy).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("approvals: create request: %w", err)
	}
	if _, err := tx.ApprovalStepAction.Create().
		SetTenantID(tenantID).SetRequestID(req.ID).SetSequence(1).SetName("HR review").
		SetApproverType(approvalstepaction.ApproverTypeRole).SetApproverRole(fallbackRole).
		SetStatus(approvalstepaction.StatusPending).Save(ctx); err != nil {
		return nil, fmt.Errorf("approvals: create step action: %w", err)
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("approvals: commit submit: %w", err)
	}
	s.fireEvent(ctx, tenantID, req, "approval.requested")
	return req, nil
}
