package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ExpenseClaim is an employee expense claim (legacy hrm.payroll.ExpenseClaims).
type ExpenseClaim struct {
	ent.Schema
}

func (ExpenseClaim) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("approver_id", uuid.UUID{}).Optional().Nillable(),

		field.Bool("approved").Default(false),
		field.String("category").Optional().Comment("Other | Mileage"),
		field.Time("application_date").Optional().Nillable(),
		field.Time("payment_date").Optional().Nillable(),
		field.String("attachment_url").Optional().Nillable(),
		moneyField("amount"),
		field.Bool("is_active").Default(true),
		field.Bool("is_paid").Default(false),
		field.Bool("schedule_to_payroll").Default(false),
		field.Bool("delete_status").Default(false),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ExpenseClaim) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
