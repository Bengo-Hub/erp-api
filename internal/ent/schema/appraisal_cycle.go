package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AppraisalCycle is a tenant-scoped appraisal period with a lifecycle FSM (legacy
// hrm.appraisals.AppraisalCycle).
type AppraisalCycle struct {
	ent.Schema
}

func (AppraisalCycle) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.String("name"),
		field.String("description").Optional(),
		field.Time("start_date"),
		field.Time("end_date"),
		field.Time("due_date").Optional().Nillable(),
		field.Enum("status").Values("created", "activated", "closed", "reopened").Default("created"),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (AppraisalCycle) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "status"),
	}
}
