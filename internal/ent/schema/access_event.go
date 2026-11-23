package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AccessEvent is a door event from an access-control device (rtlog push): who presented
// what at which door, and whether the door opened.
type AccessEvent struct {
	ent.Schema
}

func (AccessEvent) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("device_id", uuid.UUID{}).Comment("FK -> attendance_devices.id"),
		field.String("device_sn"),
		field.String("device_pin").Default("").Comment("User PIN; empty for unknown cards or faces"),
		field.UUID("employee_id", uuid.UUID{}).Optional().Nillable(),
		field.Time("occurred_at"),
		field.Int("door").Default(1),
		field.Enum("result").Values("granted", "denied"),
		field.Int("event_code").Default(0).Comment("ZKTeco event type code"),
		field.Int("verify_mode").Default(0),
		field.Int("in_out").Default(0).Comment("0 entry, 1 exit"),
		field.JSON("metadata", map[string]any{}).Optional(),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (AccessEvent) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("device_sn", "device_pin", "occurred_at", "door", "event_code").Unique(),
		index.Fields("tenant_id", "occurred_at"),
		index.Fields("tenant_id", "result"),
	}
}
