package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmployeeDisciplinary is an employee's disciplinary record
// (legacy hrm.employees.EmployeeDisciplinary). HR-owned.
type EmployeeDisciplinary struct {
	ent.Schema
}

func (EmployeeDisciplinary) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),

		field.Time("incident_date").Optional().Nillable(),
		field.String("category").Optional().Nillable().Comment("e.g. misconduct, attendance, performance"),
		field.Text("description").Optional().Nillable(),
		field.String("action_taken").Optional().Nillable().Comment("e.g. verbal warning, written warning, suspension"),
		field.String("status").Default("open").Comment("open | resolved | closed"),
		field.String("document_url").Optional().Nillable().Comment("Relative media path"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmployeeDisciplinary) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
