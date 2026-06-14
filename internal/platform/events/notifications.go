package events

import (
	"context"

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
type EmailRequest struct {
	To          []string          `json:"to"`
	Subject     string            `json:"subject"`
	Body        string            `json:"body"`
	HTML        bool              `json:"html"`
	Attachments []EmailAttachment `json:"attachments,omitempty"`
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
	payload := map[string]any{
		"to": req.To, "subject": req.Subject, "body": req.Body, "html": req.HTML,
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
	return n.pub.Publish(ctx, tenantID, aggregateID, "email.requested", payload)
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
	return n.pub.Publish(ctx, tenantID, aggregateID, "notification.requested", payload)
}
