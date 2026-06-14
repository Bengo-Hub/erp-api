package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Appraisal is an employee's appraisal within a cycle with an FSM (legacy
// hrm.appraisals.Appraisal). Tenant-scoped. overall_rating is decimal 0-5.
type Appraisal struct {
	ent.Schema
}

func (Appraisal) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("cycle_id", uuid.UUID{}).Comment("FK -> appraisal_cycles.id"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("evaluator_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("template_id", uuid.UUID{}).Optional().Nillable(),
		field.Enum("status").Values("draft", "in_progress", "completed", "approved", "rejected").Default("draft"),
		ratingFieldOptional("overall_rating"),
		field.String("comments").Optional(),
		field.String("rejection_reason").Optional().Nillable(),
		field.Time("approved_at").Optional().Nillable(),
		field.Time("rejected_at").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (Appraisal) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "cycle_id"),
		index.Fields("tenant_id", "employee_id"),
	}
}
