package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmployeeBenefit is a benefit assigned to an employee (legacy hrm.payroll.Benefits).
// Non-cash benefits feed the "final" deduction phase.
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
