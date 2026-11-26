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
// from stored values. Money is decimal.
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

		// KRA relief inputs (per-employee monthly amounts; default 0 = no relief). The engine
		// applies the statutory caps (from PayrollRelief), so these hold the ACTUAL amounts:
		//   - insurance_premium: life/health/education premiums -> 15% relief, cap 5,000/mo
		//   - pension_contribution: registered scheme contribution -> deductible pre-tax, cap 30,000/mo
		//   - mortgage_interest: owner-occupier interest -> deductible pre-tax, cap 25,000/mo
		//   - disability_exempt: holds a PWD exemption certificate (first 150,000/mo exempt)
		moneyField("insurance_premium"),
		moneyField("pension_contribution"),
		moneyField("mortgage_interest"),
		field.Bool("disability_exempt").Default(false).Comment("Holds a PWD tax-exemption certificate"),

		field.UUID("bank_account_id", uuid.UUID{}).Optional().Nillable().Comment("Primary salary bank account"),

		// Preferred net-pay disbursement channel, honoured by the payroll disburse flow when it
		// requests payout from treasury. Default bank_transfer preserves prior behaviour.
		field.String("preferred_payout_method").
			Default("bank_transfer").
			Comment("bank_transfer | mpesa_b2c | airtel | paystack_mobile | cash"),
		// payout_phone is the mobile-money MSISDN used when preferred_payout_method is a mobile
		// channel (mpesa_b2c/airtel/paystack_mobile). Bank transfers use bank_account_id.
		field.String("payout_phone").Optional().Comment("Mobile-money number for mobile payout channels"),

		field.UUID("job_group_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("workers_union_id", uuid.UUID{}).Optional().Nillable(),

		field.Bool("is_active").Default(true),
		// effective_from is the first month this salary applies. Payroll pays each month from the
		// row in force that month, so a raise can be scheduled ahead and history is kept. Empty
		// means in force from the start (rows saved before effective dates existed).
		field.Time("effective_from").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (SalaryDetails) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
		index.Fields("tenant_id", "employee_id", "effective_from"),
	}
}
