package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Candidate is a tenant-scoped recruitment candidate (legacy hrm.recruitment.Candidate).
type Candidate struct {
	ent.Schema
}

func (Candidate) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.String("full_name"),
		field.String("email"),
		field.String("phone").Optional().Nillable(),
		field.String("resume_url").Optional().Nillable().Comment("Relative media path to the resume file"),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (Candidate) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "email"),
	}
}
