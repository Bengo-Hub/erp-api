package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ShiftRoster is a recurring roster pattern resolved by cycle_days + start_date via
// ((date-start_date) % cycle_days)+1 (legacy shift_planner_models.ShiftRoster).
// Tenant-scoped.
type ShiftRoster struct {
	ent.Schema
}

func (ShiftRoster) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("outlet_id", uuid.UUID{}).Optional().Nillable(),
		field.String("name"),
		field.Int("cycle_days").Default(14),
		field.Time("start_date").Comment("Calendar anchor for cycle_day resolution"),
		field.Bool("is_active").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ShiftRoster) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "is_active"),
	}
}
