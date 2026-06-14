package schema

import (
	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PayrollSplitRatio is the employee/employer contribution split for a formula
// (legacy SplitRatio). Percentages are decimals (e.g. 50.00 = 50%).
type PayrollSplitRatio struct {
	ent.Schema
}

func (PayrollSplitRatio) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("formula_id", uuid.UUID{}).Comment("FK -> payroll_formula.id"),

		rateField("employee_percentage"),
		rateField("employer_percentage"),
	}
}

func (PayrollSplitRatio) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("formula_id"),
	}
}
