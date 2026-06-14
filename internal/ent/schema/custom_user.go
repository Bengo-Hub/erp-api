package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// CustomUser is the thin SSO user shadow keyed on external_id (= JWT sub). (ERD §1)
// auth-api owns identity; erp-api stores only what HR doc-approval / RBAC needs.
type CustomUser struct {
	ent.Schema
}

func (CustomUser) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).
			Comment("Owning tenant (auth_tenant.id)"),
		field.String("external_id").
			NotEmpty().
			Unique().
			Comment("JWT sub from auth-api (SSO identity link)"),
		field.String("email").
			NotEmpty(),
		field.String("first_name").Optional(),
		field.String("last_name").Optional(),
		field.String("middle_name").Optional(),
		field.String("phone").Optional(),
		field.String("signature_url").
			Optional().
			Comment("Stored signature image for document approvals"),
		field.String("timezone").
			Optional(),
		field.Bool("is_active").Default(true),
		field.Bool("is_staff").Default(false),
		field.Bool("is_superuser").Default(false),
		field.String("sync_status").
			Default("synced").
			Comment("synced | pending | failed"),
		field.Time("last_sync_at").
			Optional().
			Nillable(),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
		field.Time("updated_at").
			Default(time.Now).
			UpdateDefault(time.Now),
	}
}

func (CustomUser) Edges() []ent.Edge {
	return []ent.Edge{
		edge.To("role_assignments", UserRoleAssignment.Type),
	}
}

func (CustomUser) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("external_id").Unique(),
		index.Fields("tenant_id"),
		index.Fields("email"),
		index.Fields("tenant_id", "email"),
	}
}
