package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// BankInstitution is reference data (core.BankInstitution, ERD §3). System-wide bank list.
type BankInstitution struct {
	ent.Schema
}

func (BankInstitution) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.String("name").NotEmpty(),
		field.String("code").
			Optional().
			Comment("Bank code (unique when present)"),
		field.String("short_code").Optional(),
		field.String("swift_code").Optional(),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
	}
}

func (BankInstitution) Edges() []ent.Edge {
	return []ent.Edge{
		edge.To("branches", BankBranch.Type),
	}
}

func (BankInstitution) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("code").Unique(),
		index.Fields("name"),
	}
}
