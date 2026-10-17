package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmployeeLoan is a loan issued to an employee (legacy hrm.payroll.EmployeLoans).
// Recovery is computed purely by the engine (no save() inside calc).
type EmployeeLoan struct {
	ent.Schema
}

func (EmployeeLoan) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("loan_type_id", uuid.UUID{}).Optional().Nillable(),

		moneyField("principal_amount"),
		moneyField("amount_repaid"),
		moneyField("interest_paid"),
		field.Int("no_of_installments_paid").Default(0),
		moneyField("monthly_installment"),
		rateField("interest_rate"),
		field.String("interest_formula").Optional().Nillable().Comment("Reducing Balance | Fixed"),
		field.Bool("is_active").Default(false),
		field.Time("start_date").Optional().Nillable(),
		field.Time("end_date").Optional().Nillable(),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmployeeLoan) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
		index.Fields("employee_id", "is_active"),
	}
}
