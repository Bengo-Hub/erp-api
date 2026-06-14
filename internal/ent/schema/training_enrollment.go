package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TrainingEnrollment is an employee's enrollment in a course (legacy
// hrm.training.TrainingEnrollment). Tenant-scoped; unique per (tenant, course, employee).
// Capacity enforcement lives in the service (count enrolled < course.capacity).
type TrainingEnrollment struct {
	ent.Schema
}

func (TrainingEnrollment) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("course_id", uuid.UUID{}).Comment("FK -> training_courses.id"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.Enum("status").Values("enrolled", "completed", "cancelled").Default("enrolled"),
		field.Time("enrolled_at").Default(time.Now),
	}
}

func (TrainingEnrollment) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "course_id", "status"),
		index.Fields("tenant_id", "course_id", "employee_id").Unique(),
	}
}
