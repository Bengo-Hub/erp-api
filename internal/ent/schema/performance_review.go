package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PerformanceReview is an employee review with an FSM (legacy
// hrm.performance.PerformanceReview). Tenant-scoped. overall_rating is decimal 0-5.
type PerformanceReview struct {
	ent.Schema
}

func (PerformanceReview) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.String("title"),
		field.String("description").Optional(),
		field.Time("review_date"),
		field.Enum("status").Values("draft", "in_progress", "completed", "approved", "rejected").Default("draft"),
		ratingFieldOptional("overall_rating"),
		field.String("comments").Optional(),
		field.UUID("reviewer_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (PerformanceReview) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id"),
		index.Fields("tenant_id", "status"),
	}
}
