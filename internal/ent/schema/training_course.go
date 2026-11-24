package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TrainingCourse is a tenant-scoped training course/program (legacy
// hrm.training.TrainingCourse). capacity 0 = unlimited.
type TrainingCourse struct {
	ent.Schema
}

func (TrainingCourse) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.String("title"),
		field.String("description").Optional(),
		field.Time("start_date"),
		field.Time("end_date"),
		field.Int("capacity").Default(0).Comment("0 = unlimited"),
		// Metadata holds course attributes without their own column: provider, duration,
		// cost and status.
		field.JSON("metadata", map[string]any{}).Optional(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (TrainingCourse) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "start_date"),
	}
}
