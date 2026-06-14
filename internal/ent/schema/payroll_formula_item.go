package schema

import (
	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PayrollFormulaItem is a bracket/band of a PayrollFormula (legacy FormulaItems).
type PayrollFormulaItem struct {
	ent.Schema
}

func (PayrollFormulaItem) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (denormalised for scoping)"),
		field.UUID("formula_id", uuid.UUID{}).Comment("FK -> payroll_formula.id"),

		moneyField("amount_from"),
		moneyField("amount_to"),
		moneyField("deduct_amount"),
		rateField("deduct_percentage"),
	}
}

func (PayrollFormulaItem) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("formula_id"),
	}
}
