package payroll

import (
	"context"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Claim lifecycle events for treasury budgets. A pending claim is money the business has agreed
// to pay back, so treasury holds it as a budget commitment:
//   - erp.expense_claim.created / .updated open or resize the commitment,
//   - erp.expense_claim.approved books the reimbursement and consumes it,
//   - erp.expense_claim.deleted releases it.
// The payload is the one treasury's claimApprovedPayload reads, plus approved and
// application_date.

// WithLogger sets the logger used for best-effort event failures. Optional.
func (s *Service) WithLogger(log *zap.Logger) *Service {
	s.log = log
	return s
}

func claimPayload(c *ent.ExpenseClaim) map[string]any {
	projectID := ""
	if c.ProjectID != nil {
		projectID = c.ProjectID.String()
	}
	p := map[string]any{
		"claim_id":    c.ID.String(),
		"tenant_id":   c.TenantID.String(),
		"employee_id": c.EmployeeID.String(),
		"amount":      c.Amount.StringFixed(2),
		"currency":    "KES",
		"claim_type":  c.ClaimType,
		"taxable":     c.Taxable,
		"category":    c.Category,
		"project_id":  projectID,
		"approved":    c.Approved,
	}
	if c.CostCenterID != nil {
		p["cost_center_id"] = c.CostCenterID.String()
	}
	if c.ApplicationDate != nil {
		p["application_date"] = c.ApplicationDate.Format(time.DateOnly)
	}
	return p
}

// publishClaimBestEffort emits a claim event without failing the caller: the claim is saved, and
// a lost event only means the budget does not show the claim as committed until it is approved.
func (s *Service) publishClaimBestEffort(ctx context.Context, tenantID, claimID uuid.UUID, eventType string, payload map[string]any) {
	if s.publisher == nil {
		return
	}
	if err := s.publisher.Publish(ctx, tenantID, claimID, eventType, payload); err != nil && s.log != nil {
		s.log.Warn("claim event not published", zap.String("event", eventType), zap.String("claim_id", claimID.String()), zap.Error(err))
	}
}
