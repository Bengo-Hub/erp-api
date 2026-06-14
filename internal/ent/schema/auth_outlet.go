package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AuthOutlet is the local shadow of an auth-api outlet (branch). (ERD §1)
type AuthOutlet struct {
	ent.Schema
}

func (AuthOutlet) Fields() []ent.Field {
	return []ent.Field{
		// PK is the auth-api outlet UUID.
		field.UUID("id", uuid.UUID{}).
			Immutable().
			Comment("auth-api outlet UUID"),
		field.UUID("tenant_id", uuid.UUID{}).
			Comment("Owning tenant (auth_tenant.id)"),
		field.String("code").
			Optional().
			Comment("Outlet code"),
		field.String("name").
			NotEmpty(),
		field.String("use_case").
			Optional().
			Comment("hospitality | retail | quick_service | ..."),
		field.Bool("is_hq").
			Default(false),
		field.String("status").
			Default("active").
			Comment("active | archived"),
		field.String("timezone").
			Optional(),
		field.Time("synced_at").
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

func (AuthOutlet) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("tenant", AuthTenant.Type).
			Ref("outlets").
			Field("tenant_id").
			Required().
			Unique(),
	}
}

func (AuthOutlet) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "code"),
		index.Fields("status"),
	}
}
