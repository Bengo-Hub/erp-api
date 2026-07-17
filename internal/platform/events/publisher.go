package events

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	eventslib "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Publisher writes domain events to the transactional outbox (outbox_events table).
// The shared-events OutboxPoller drains PENDING rows to NATS — this replaces
// the Django integrations.events.publish_event + drain_outbox path.
//
// Subject convention (docs/integrations.md §1): "{aggregate_type}.{event_type}",
// e.g. aggregate_type="erp", event_type="payroll.processed" -> subject "erp.payroll.processed".
//
// The payload column MUST hold the FULL shared-events envelope (Event.ToJSON()), not the
// bare business payload: the poller rebuilds the event solely via FromJSON(payload) and
// derives the subject from the deserialized envelope — a bare payload yields subject "."
// and the event is silently lost.
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

// AggregateUUID returns ref parsed as a UUID, or a stable SHA1-derived UUID (namespaced by
// tenant) when it isn't one. The shared-events poller scans aggregate_id into uuid.UUID, so
// a non-UUID value jams the entire poll batch — every aggregate_id MUST go through this (or
// already be a uuid.UUID).
func AggregateUUID(tenantID uuid.UUID, ref string) uuid.UUID {
	if id, err := uuid.Parse(ref); err == nil {
		return id
	}
	return uuid.NewSHA1(tenantID, []byte(ref))
}

// Publish writes a single event row to the outbox inside the caller's context.
// Pass a transactional ent client (tx.Client()) to make the write atomic with the
// domain mutation. eventType must NOT repeat the aggregate prefix ("payroll.processed",
// never "erp.payroll.processed" — that would double the subject).
func (p *Publisher) Publish(ctx context.Context, tenantID, aggregateID uuid.UUID, eventType string, payload map[string]any) error {
	if p == nil || p.orm == nil {
		return fmt.Errorf("events: publisher not initialised")
	}
	ev := eventslib.NewEvent(eventType, p.source, aggregateID, tenantID, payload)
	raw, err := ev.ToJSON()
	if err != nil {
		return fmt.Errorf("events: marshal envelope: %w", err)
	}

	_, err = p.orm.OutboxEvent.Create().
		SetID(ev.ID).
		SetTenantID(tenantID).
		SetAggregateType(p.source).
		SetAggregateID(aggregateID.String()).
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
