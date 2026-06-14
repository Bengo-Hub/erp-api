package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// WithHoldingTax is a tenant-scoped withholding-tax rate (legacy WithHoldingtax).
type WithHoldingTax struct {
	ent.Schema
}

func (WithHoldingTax) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),

		field.String("title").Default("Default Tax"),
		rateField("rate"),       // tax rate percentage
		moneyField("threshold"), // minimum amount for tax application
		field.Bool("is_active").Default(true),
		field.Time("effective_from").Optional().Nillable(),
		field.Time("effective_to").Optional().Nillable(),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (WithHoldingTax) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "is_active"),
	}
}
