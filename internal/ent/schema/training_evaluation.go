package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TrainingEvaluation is an employee's post-course feedback (legacy
// hrm.training.TrainingEvaluation). Tenant-scoped. rating 0-5.
type TrainingEvaluation struct {
	ent.Schema
}

func (TrainingEvaluation) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("course_id", uuid.UUID{}).Comment("FK -> training_courses.id"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.Int("rating").Default(0).Comment("0-5"),
		field.String("feedback").Optional(),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (TrainingEvaluation) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "course_id"),
	}
}
