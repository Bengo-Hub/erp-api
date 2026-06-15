package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmploymentHistory is an employee's prior-employment record
// (legacy hrm.employees.EmploymentHistory). HR-owned.
type EmploymentHistory struct {
	ent.Schema
}

func (EmploymentHistory) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),

		field.String("employer").NotEmpty(),
		field.String("designation").Optional().Nillable().Comment("Job title held"),
		field.Time("start_date").Optional().Nillable(),
		field.Time("end_date").Optional().Nillable(),
		field.String("reason_for_leaving").Optional().Nillable(),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmploymentHistory) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
