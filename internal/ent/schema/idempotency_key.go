package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// IdempotencyKey backs idempotent handling of consumers and S2S disburse calls
// (sprint spec §Ent schemas). A processed key short-circuits duplicate work.
type IdempotencyKey struct {
	ent.Schema
}

func (IdempotencyKey) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.String("key").
			NotEmpty().
			Unique().
			Comment("Idempotency key (e.g. event id or client-supplied Idempotency-Key)"),
		field.String("scope").
			Default("default").
			Comment("Namespace, e.g. consumer subject or endpoint"),
		field.UUID("tenant_id", uuid.UUID{}).
			Optional().
			Nillable(),
		field.String("status").
			Default("processed").
			Comment("processing | processed | failed"),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
	}
}

func (IdempotencyKey) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("key").Unique(),
		index.Fields("scope"),
		index.Fields("created_at"),
	}
}
