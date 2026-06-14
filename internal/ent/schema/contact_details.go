package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ContactDetails holds an employee's contact info (legacy hrm.employees.ContactDetails).
type ContactDetails struct {
	ent.Schema
}

func (ContactDetails) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),

		field.String("personal_email").Optional().Nillable(),
		field.String("phone").Optional().Nillable(),
		field.String("alternate_phone").Optional().Nillable(),
		field.String("postal_address").Optional().Nillable(),
		field.String("physical_address").Optional().Nillable(),
		field.String("city").Optional().Nillable(),
		field.String("country").Optional().Nillable(),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ContactDetails) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
