package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ClaimItem is a line item of an ExpenseClaim (legacy hrm.payroll.ClaimItems).
type ClaimItem struct {
	ent.Schema
}

func (ClaimItem) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("expense_claim_id", uuid.UUID{}).Comment("FK -> expense_claim.id"),

		field.String("expense_type").Optional().Comment("tt | ac | ml | jm | os | mh | tr | mlg"),
		field.String("description").Optional().Nillable(),
		moneyField("amount"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ClaimItem) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("expense_claim_id"),
	}
}
