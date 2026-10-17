package schema

import (
	"encoding/json"
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// OutboxEvent is the transactional outbox table drained by shared-events OutboxPoller.
type OutboxEvent struct {
	ent.Schema
}

func (OutboxEvent) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).
			Comment("Tenant ID for scoping; uuid.Nil for global events"),
		field.String("aggregate_type").
			NotEmpty().
			Comment("Event source/aggregate prefix, e.g. \"erp\""),
		field.String("aggregate_id").
			NotEmpty().
			Comment("Aggregate reference: batch ref / object UUID"),
		field.String("event_type").
			NotEmpty().
			Comment("e.g. payroll.processed (subject = aggregate_type.event_type)"),
		field.JSON("payload", json.RawMessage{}).
			Comment("Serialized event payload — raw JSON"),
		field.String("status").
			Default("PENDING").
			Comment("PENDING | PUBLISHED | FAILED"),
		field.Int("attempts").
			Default(0),
		field.Time("last_attempt_at").
			Optional().
			Nillable(),
		field.Time("published_at").
			Optional().
			Nillable(),
		field.Text("error_message").
			Optional().
			Nillable(),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
	}
}

func (OutboxEvent) Edges() []ent.Edge { return nil }

func (OutboxEvent) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("status"),
		index.Fields("created_at"),
		index.Fields("tenant_id", "status"),
	}
}
