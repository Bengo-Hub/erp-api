package events

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Publisher writes domain events to the transactional outbox (outbox_events table).
// The shared-events OutboxPoller drains PENDING rows to NATS JetStream — this replaces
// the Django integrations.events.publish_event + drain_outbox path.
//
// Subject convention (docs/integrations.md §1): "{aggregate_type}.{event_type}",
// e.g. aggregate_type="erp", event_type="payroll.processed" -> subject "erp.payroll.processed".
type Publisher struct {
	orm    *ent.Client
	source string
}

// NewPublisher builds an outbox publisher. source is the aggregate_type/source prefix
// (EVENTS_SOURCE_SERVICE, default "erp").
func NewPublisher(orm *ent.Client, source string) *Publisher {
	if source == "" {
		source = "erp"
	}
	return &Publisher{orm: orm, source: source}
}

// Publish writes a single event row to the outbox inside the caller's context.
// Pass a transactional ent client (tx.Client()) to make the write atomic with the
// domain mutation. aggregateID is a free-form reference (batch ref / object UUID).
func (p *Publisher) Publish(ctx context.Context, tenantID uuid.UUID, aggregateID, eventType string, payload map[string]any) error {
	if p == nil || p.orm == nil {
		return fmt.Errorf("events: publisher not initialised")
	}
	raw, err := json.Marshal(payload)
	if err != nil {
		return fmt.Errorf("events: marshal payload: %w", err)
	}

	_, err = p.orm.OutboxEvent.Create().
		SetID(uuid.New()).
		SetTenantID(tenantID).
		SetAggregateType(p.source).
		SetAggregateID(aggregateID).
		SetEventType(eventType).
		SetPayload(json.RawMessage(raw)).
		SetStatus("PENDING").
		SetCreatedAt(time.Now().UTC()).
		Save(ctx)
	if err != nil {
		return fmt.Errorf("events: write outbox row: %w", err)
	}
	return nil
}
