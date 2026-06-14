package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AuthTenant is the local shadow of an auth-api tenant. Auth-api is the source of truth;
// this stores the minimal reference for FK relationships and routing. (ERD §1)
type AuthTenant struct {
	ent.Schema
}

func (AuthTenant) Fields() []ent.Field {
	return []ent.Field{
		// PK is the auth-api tenant UUID (NOT generated locally).
		field.UUID("id", uuid.UUID{}).
			Immutable().
			Comment("auth-api tenant UUID"),
		field.String("slug").
			NotEmpty().
			Unique().
			Comment("URL-safe identifier — synced from auth-api"),
		field.String("name").
			NotEmpty(),
		field.Bool("is_platform").
			Default(false),
		field.String("status").
			Default("active").
			Comment("active | inactive | suspended"),
		field.Time("synced_at").
			Optional().
			Nillable().
			Comment("Last successful sync from auth-api"),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
		field.Time("updated_at").
			Default(time.Now).
			UpdateDefault(time.Now),
	}
}

func (AuthTenant) Edges() []ent.Edge {
	return []ent.Edge{
		edge.To("outlets", AuthOutlet.Type),
	}
}

func (AuthTenant) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("slug").Unique(),
		index.Fields("status"),
	}
}
