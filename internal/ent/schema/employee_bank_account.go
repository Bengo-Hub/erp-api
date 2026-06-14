package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmployeeBankAccount is an employee's bank account (legacy hrm.employees.EmployeeBankAccount).
// "Single primary per employee" is enforced in a tx by the service (port of the Django
// EmployeeBankAccountViewSet behaviour).
type EmployeeBankAccount struct {
	ent.Schema
}

func (EmployeeBankAccount) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("bank_institution_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("bank_branch_id", uuid.UUID{}).Optional().Nillable(),

		field.String("account_name").NotEmpty(),
		field.String("account_number").NotEmpty(),
		field.String("account_type").Default("savings").Comment("savings | current | ..."),
		field.Bool("is_primary").Default(false).Comment("Primary salary account (one per employee)"),
		field.String("status").Default("active"),
		field.Bool("is_verified").Default(false),
		field.Time("opened_date").Optional().Nillable(),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmployeeBankAccount) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
		index.Fields("employee_id", "is_primary"),
	}
}
