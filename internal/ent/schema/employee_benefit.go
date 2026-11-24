package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmployeeBenefit is a payroll component assigned to an employee (legacy hrm.payroll.Benefits,
// Earnings and Deductions). The component's category decides how a run applies it: non-cash
// benefits feed the "final" deduction phase, earnings add to gross and deductions come off net
// pay. Values the row has no column for live in metadata (percentage, percent_of, reference).
type EmployeeBenefit struct {
	ent.Schema
}

func (EmployeeBenefit) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("component_id", uuid.UUID{}).Optional().Nillable().Comment("PayrollComponent benefit"),

		moneyField("amount"),
		field.Bool("non_cash").Default(false),
		field.Bool("is_active").Default(true),
		field.Time("effective_date").Optional().Nillable(),
		field.Time("end_date").Optional().Nillable(),
		field.JSON("metadata", map[string]any{}).Optional().
			Comment("percentage, percent_of (basic | gross) and reference (scheme or membership number)"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmployeeBenefit) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
		index.Fields("employee_id", "is_active"),
	}
}
