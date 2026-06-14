package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// HRDetails holds an employee's org placement (legacy hrm.employees.HRDetails).
type HRDetails struct {
	ent.Schema
}

func (HRDetails) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),

		field.UUID("job_title_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("department_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("head_of_department_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("reports_to_id", uuid.UUID{}).Optional().Nillable().Comment("Manager employee.id"),
		field.UUID("region_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("project_id", uuid.UUID{}).Optional().Nillable(),

		field.String("employment_type").Optional().Comment("permanent | contract | casual | consultant"),
		field.Time("date_joined").Optional().Nillable(),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (HRDetails) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
