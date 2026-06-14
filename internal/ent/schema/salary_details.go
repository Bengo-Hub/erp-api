package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// SalaryDetails holds an employee's pay setup (legacy hrm.employees.SalaryDetails).
// Derived rates (hourly/daily) are recomputed on write by the service, never trusted
// from stored values (data-migration §4 stale-derived fix). Money is decimal.
type SalaryDetails struct {
	ent.Schema
}

func (SalaryDetails) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (auth_tenant.id)"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),

		moneyField("monthly_salary"),
		field.String("pay_mode").Optional().Comment("monthly | weekly | daily | perhour | perday"),
		field.String("income_tax").Default("primary").Comment("primary | secondary | none (PAYE category)"),
		field.String("currency").Default("KES"),

		// Recomputed derived rates (not trusted from input).
		moneyField("hourly_rate"),
		moneyField("daily_rate"),

		field.UUID("bank_account_id", uuid.UUID{}).Optional().Nillable().Comment("Primary salary bank account"),
		field.UUID("job_group_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("workers_union_id", uuid.UUID{}).Optional().Nillable(),

		field.Bool("is_active").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (SalaryDetails) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
	}
}
