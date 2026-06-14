package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// GoalProgress is a progress-update entry for a Goal (legacy hrm.appraisals.GoalProgress).
// Tenant-scoped. progress 0-100.
type GoalProgress struct {
	ent.Schema
}

func (GoalProgress) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("goal_id", uuid.UUID{}).Comment("FK -> goals.id"),
		field.Int("progress").Comment("0-100"),
		field.String("comments").Optional(),
		field.UUID("updated_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (GoalProgress) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "goal_id"),
	}
}
