package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// UserRoleAssignment links a CustomUser to a Role within a tenant.
type UserRoleAssignment struct {
	ent.Schema
}

func (UserRoleAssignment) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.UUID("tenant_id", uuid.UUID{}),
		field.UUID("user_id", uuid.UUID{}).
			Comment("custom_user.id"),
		field.UUID("role_id", uuid.UUID{}),
		field.Time("assigned_at").
			Default(time.Now).
			Immutable(),
		field.Time("expires_at").
			Optional().
			Nillable(),
		field.String("source").
			Default("sync").
			Comment("sync: from the SSO token, which adds and removes it; erp: given in ERP, sync leaves it"),
	}
}

func (UserRoleAssignment) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("user", CustomUser.Type).
			Ref("role_assignments").
			Field("user_id").
			Required().
			Unique(),
		edge.From("role", Role.Type).
			Ref("user_assignments").
			Field("role_id").
			Required().
			Unique(),
	}
}

func (UserRoleAssignment) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "user_id", "role_id").Unique(),
		index.Fields("tenant_id"),
		index.Fields("user_id"),
		index.Fields("role_id"),
	}
}
