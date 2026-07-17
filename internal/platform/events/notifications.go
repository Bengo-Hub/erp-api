package events

import (
	"context"
	"time"

	"github.com/google/uuid"
)

// Notifications wraps the outbox Publisher to emit the two notification subjects the
// notifications-api consumes (erp_handlers.go): erp.email.requested (supports attachments,
// e.g. payslip PDFs) and erp.notification.requested. erp-api NEVER sends email/SMS directly
// (plan §0a-map) — it only publishes these events.
type Notifications struct {
	pub *Publisher
}

// NewNotifications builds the notifications emitter over the outbox publisher (source "erp").
func NewNotifications(pub *Publisher) *Notifications { return &Notifications{pub: pub} }

// EmailRequest is the payload for erp.email.requested. Attachments are base64-encoded.
// DeliverAt, when set (future), asks the email worker to hold delivery until then
// (scheduled/mass email); empty = deliver as soon as the outbox drains.
type EmailRequest struct {
	To          []string          `json:"to"`
	Subject     string            `json:"subject"`
	Body        string            `json:"body"`
	HTML        bool              `json:"html"`
	Attachments []EmailAttachment `json:"attachments,omitempty"`
	DeliverAt   *time.Time        `json:"deliver_at,omitempty"`
}

// EmailAttachment is a base64-encoded file attachment (e.g. a payslip PDF).
type EmailAttachment struct {
	Filename    string `json:"filename"`
	ContentType string `json:"content_type"`
	ContentB64  string `json:"content_base64"`
}

// RequestEmail publishes erp.email.requested to the outbox (atomic with the caller's tx when
// a transactional client is used). aggregateID groups related emails (e.g. a payroll batch).
func (n *Notifications) RequestEmail(ctx context.Context, tenantID uuid.UUID, aggregateID string, req EmailRequest) error {
	if n == nil || n.pub == nil {
		return nil
	}
	// Match notifications-api's erp.email.requested contract exactly (recipient_list /
	// message / html_message). The previous keys (to/body/html) were silently dropped by
	// the consumer as "no valid recipients", so every payslip / voucher / candidate email
	// went nowhere. req.HTML is a flag meaning "Body is HTML".
	payload := map[string]any{
		"recipient_list": req.To,
		"subject":        req.Subject,
		"message":        req.Body,
	}
	if req.HTML {
		payload["html_message"] = req.Body
	}
	if len(req.Attachments) > 0 {
		atts := make([]map[string]any, 0, len(req.Attachments))
		for _, a := range req.Attachments {
			atts = append(atts, map[string]any{
				"filename": a.Filename, "content_type": a.ContentType, "content_base64": a.ContentB64,
			})
		}
		payload["attachments"] = atts
	}
	if req.DeliverAt != nil {
		payload["deliver_at"] = req.DeliverAt.Format(time.RFC3339)
	}
	return n.pub.Publish(ctx, tenantID, AggregateUUID(tenantID, aggregateID), "email.requested", payload)
}

// NotificationRequest is the payload for erp.notification.requested (in-app/multi-channel).
type NotificationRequest struct {
	UserID           string         `json:"user_id"`
	Title            string         `json:"title"`
	Message          string         `json:"message"`
	NotificationType string         `json:"notification_type"`
	Channels         []string       `json:"channels"`
	Data             map[string]any `json:"data,omitempty"`
}

// RequestNotification publishes erp.notification.requested to the outbox.
func (n *Notifications) RequestNotification(ctx context.Context, tenantID uuid.UUID, aggregateID string, req NotificationRequest) error {
	if n == nil || n.pub == nil {
		return nil
	}
	payload := map[string]any{
		"user_id": req.UserID, "title": req.Title, "message": req.Message,
		"notification_type": req.NotificationType, "channels": req.Channels,
	}
	if req.Data != nil {
		payload["data"] = req.Data
	}
	return n.pub.Publish(ctx, tenantID, AggregateUUID(tenantID, aggregateID), "notification.requested", payload)
}
