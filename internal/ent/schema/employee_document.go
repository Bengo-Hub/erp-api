package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmployeeDocument is an uploaded HR document (legacy hrm.employees.Documents).
type EmployeeDocument struct {
	ent.Schema
}

func (EmployeeDocument) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),

		field.String("title").NotEmpty(),
		field.String("document_type").Optional().Nillable(),
		field.String("file_url").Optional().Nillable().Comment("Relative media path (resolved at read)"),
		field.Time("expiry_date").Optional().Nillable(),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmployeeDocument) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
