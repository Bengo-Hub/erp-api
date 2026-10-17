package leave

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
)

// outboxNotifier emits erp.notification.requested for leave decisions via the transactional
// outbox . Payload shape follows integrations.md §1
// (notifications-api contract). Best-effort: callers ignore the error (logged upstream).
type outboxNotifier struct {
	pub *events.Publisher
}

// NewOutboxNotifier builds a Notifier backed by the outbox Publisher. Pass the publisher
// configured with source "erp" so the emitted subject is erp.notification.requested.
func NewOutboxNotifier(pub *events.Publisher) Notifier {
	return &outboxNotifier{pub: pub}
}

func (n *outboxNotifier) NotifyLeaveDecision(ctx context.Context, tenantID uuid.UUID, req *ent.LeaveRequest) error {
	if n == nil || n.pub == nil {
		return nil
	}
	title := "Leave request " + string(req.Status)
	msg := fmt.Sprintf("Your leave request (%s to %s) was %s.",
		req.StartDate.Format("2006-01-02"), req.EndDate.Format("2006-01-02"), req.Status)
	payload := map[string]any{
		"user_id":           req.EmployeeID.String(),
		"title":             title,
		"message":           msg,
		"notification_type": "leave_decision",
		"channels":          []string{"in_app", "email"},
		"data": map[string]any{
			"leave_request_id": req.ID.String(),
			"status":           string(req.Status),
			"start_date":       req.StartDate.Format("2006-01-02"),
			"end_date":         req.EndDate.Format("2006-01-02"),
		},
	}
	return n.pub.Publish(ctx, tenantID, req.ID, "notification.requested", payload)
}
