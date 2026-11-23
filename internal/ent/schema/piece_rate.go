package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PieceRate is the pay for one unit of an operation or item (per piece, per kg, per crate),
// optionally for one department, valid between effective dates.
type PieceRate struct {
	ent.Schema
}

func (PieceRate) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.String("code"),
		field.String("name"),
		field.String("unit").Comment("piece, kg, crate, ..."),
		moneyField("rate"),
		field.String("currency"),
		field.UUID("department_id", uuid.UUID{}).Optional().Nillable(),
		field.Time("effective_from"),
		field.Time("effective_to").Optional().Nillable(),
		field.Bool("active").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (PieceRate) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "code"),
	}
}
