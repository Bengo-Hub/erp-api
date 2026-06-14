package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Project is reference data (core.Projects, ERD §3).
type Project struct {
	ent.Schema
}

func (Project) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).
			Optional().
			Nillable(),
		field.String("code").Optional(),
		field.String("title").NotEmpty(),
		field.String("category").
			Optional().
			Comment("Project category title (core.ProjectCategory collapsed to a string)"),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
	}
}

func (Project) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("code"),
	}
}
