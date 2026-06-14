package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// BenefitTax is a tenant-scoped fringe-benefit tax config (legacy BenefitTaxes).
type BenefitTax struct {
	ent.Schema
}

func (BenefitTax) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),

		field.String("title").NotEmpty(),
		field.Bool("actual_amount").Default(true),
		moneyField("fixed_limit"),
		rateField("percentage"),
		field.String("percent_of").Optional().Nillable(),
		moneyField("amounts_greater_than"),
		moneyField("min_taxable_aggregate"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (BenefitTax) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
	}
}
