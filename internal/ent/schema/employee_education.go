package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmployeeEducation is an employee's education/qualification record
// (legacy hrm.employees.EmployeeEducation). HR-owned.
type EmployeeEducation struct {
	ent.Schema
}

func (EmployeeEducation) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),

		field.String("institution").NotEmpty(),
		field.String("qualification").Optional().Nillable().Comment("Degree/diploma/certificate name"),
		field.String("field_of_study").Optional().Nillable(),
		field.String("grade").Optional().Nillable(),
		field.Time("start_date").Optional().Nillable(),
		field.Time("end_date").Optional().Nillable(),
		field.String("certificate_url").Optional().Nillable().Comment("Relative media path"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmployeeEducation) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
