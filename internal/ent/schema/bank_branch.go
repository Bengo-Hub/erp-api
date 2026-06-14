package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// BankBranch is reference data (core.BankBranches, ERD §3). Belongs to a BankInstitution.
type BankBranch struct {
	ent.Schema
}

func (BankBranch) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.UUID("bank_id", uuid.UUID{}).
			Comment("bank_institution.id"),
		field.String("name").NotEmpty(),
		field.String("code").
			Optional().
			Comment("Branch code (unique per bank)"),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
	}
}

func (BankBranch) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("bank", BankInstitution.Type).
			Ref("branches").
			Field("bank_id").
			Required().
			Unique(),
	}
}

func (BankBranch) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("bank_id"),
		index.Fields("bank_id", "code").Unique(),
	}
}
