package approvals

import (
	"context"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
)

// outboxEmitter publishes approval lifecycle events to the transactional outbox. Approval
// events are surfaced as erp.notification.requested so notifications-api fans them out to
// approvers/requesters (integrations.md §1). Best-effort: callers ignore the error.
type outboxEmitter struct {
	pub *events.Publisher
}

// NewOutboxEmitter builds an Emitter backed by the outbox Publisher (source "erp").
func NewOutboxEmitter(pub *events.Publisher) Emitter {
	return &outboxEmitter{pub: pub}
}

func (e *outboxEmitter) EmitApprovalEvent(ctx context.Context, tenantID uuid.UUID, req *ent.ApprovalRequest, eventType string) error {
	if e == nil || e.pub == nil || req == nil {
		return nil
	}
	payload := map[string]any{
		"title":             "Approval " + req.Status.String(),
		"message":           "Approval " + eventType + " for " + req.Module.String(),
		"notification_type": eventType,
		"channels":          []string{"in_app", "email"},
		"data": map[string]any{
			"approval_request_id": req.ID.String(),
			"module":              req.Module.String(),
			"object_id":           req.ObjectID.String(),
			"status":              req.Status.String(),
			"current_sequence":    req.CurrentSequence,
		},
	}
	if req.RequesterEmployeeID != nil {
		payload["user_id"] = req.RequesterEmployeeID.String()
	}
	return e.pub.Publish(ctx, tenantID, req.ID.String(), "notification.requested", payload)
}
