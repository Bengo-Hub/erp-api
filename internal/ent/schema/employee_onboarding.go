package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmployeeOnboarding tracks a new hire's onboarding lifecycle (legacy
// hrm.recruitment.EmployeeOnboarding). Tenant-scoped. Completes when all tasks are done.
type EmployeeOnboarding struct {
	ent.Schema
}

func (EmployeeOnboarding) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.Enum("status").Values("not_started", "in_progress", "completed").Default("not_started"),
		field.Time("probation_end_date").Optional().Nillable(),
		field.Time("started_at").Optional().Nillable(),
		field.Time("completed_at").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmployeeOnboarding) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id"),
	}
}
