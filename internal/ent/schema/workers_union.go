package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// WorkersUnion is tenant-scoped HR reference data (legacy hrm.employees.WorkersUnion).
type WorkersUnion struct {
	ent.Schema
}

func (WorkersUnion) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.String("name").NotEmpty(),
		field.String("code").NotEmpty(),
		field.String("registration_number").Optional().Nillable(),
		field.String("contact_person").Optional().Nillable(),
		field.String("contact_email").Optional().Nillable(),
		field.String("contact_phone").Optional().Nillable(),
		field.Text("description").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (WorkersUnion) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		// Union code unique within a tenant, never globally.
		index.Fields("tenant_id", "code").Unique(),
	}
}
