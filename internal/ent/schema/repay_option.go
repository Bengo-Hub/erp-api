package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// RepayOption is an installment plan for advances/loss-damages (legacy RepayOption).
// installment_amount is recomputed on write (= amount / no_of_installments).
type RepayOption struct {
	ent.Schema
}

func (RepayOption) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),

		moneyField("amount"),
		field.Int("no_of_installments").Default(1),
		moneyField("installment_amount"), // recomputed = amount / no_of_installments

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (RepayOption) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
	}
}
