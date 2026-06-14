package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// NextOfKin holds an employee's kin details (legacy hrm.employees.NextOfKin).
type NextOfKin struct {
	ent.Schema
}

func (NextOfKin) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),

		field.String("full_name").NotEmpty(),
		field.String("relationship").Optional().Nillable(),
		field.String("phone").Optional().Nillable(),
		field.String("email").Optional().Nillable(),
		field.String("address").Optional().Nillable(),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (NextOfKin) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
