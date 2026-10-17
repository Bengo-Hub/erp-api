package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Payslip is a generated payroll line for one employee/period (legacy hrm.payroll.Payslip).
// ALL money is decimal. Tenant + outlet scoped for isolation.
type Payslip struct {
	ent.Schema
}

func (Payslip) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant — REQUIRED for isolation"),
		field.UUID("outlet_id", uuid.UUID{}).Optional().Nillable().Comment("Outlet scoping + disburse batch grouping"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.UUID("approver_id", uuid.UUID{}).Optional().Nillable(),

		// Core amounts.
		moneyField("gross_pay"),
		moneyField("total_earnings"),
		moneyField("net_pay"),

		// Tax fields.
		moneyField("taxable_pay"),
		moneyField("paye"),
		moneyField("tax_relief"), // personal relief
		moneyField("reliefs"),    // total reliefs applied
		moneyField("gross_pay_after_tax"),

		// Itemised KRA reliefs the engine applied (for the P9/P9A card). Default 0.
		//   - insurance_relief:     15% x premium credit (cap 5,000/mo)
		//   - pension_deduction:    deductible pension (min actual / 30% gross / 30,000)
		//   - mortgage_deduction:   owner-occupier interest (cap 30,000/mo)
		//   - disability_exemption: PWD chargeable-pay exemption applied (up to 150,000/mo)
		moneyField("insurance_relief"),
		moneyField("pension_deduction"),
		moneyField("mortgage_deduction"),
		moneyField("disability_exemption"),

		// Statutory.
		moneyField("shif_or_nhif_contribution"),
		moneyField("housing_levy"),
		moneyField("nssf_employee_tier_1"),
		moneyField("nssf_employee_tier_2"),
		moneyField("nssf_employer_contribution"),

		// Phase totals.
		moneyField("deductions_before_tax"),
		moneyField("deductions_after_tax"),
		moneyField("deductions_after_paye"),
		moneyField("deductions_final"),

		field.Time("payment_period").Optional().Nillable(),
		field.Time("period_start").Optional().Nillable(),
		field.Time("period_end").Optional().Nillable(),
		field.String("payroll_status").Default("queued").Comment("complete | expired | processing | queued"),
		field.String("approval_status").Default("draft").Comment("draft | pending | approved | rejected"),
		field.Bool("published").Default(false).Comment("Disbursed/published by treasury.payroll.disbursed"),

		// Disburse idempotency.
		field.String("batch_ref").Optional().Nillable().Comment("Disburse batch reference (set on disburse)"),

		// KRA filing metadata.
		field.String("kra_paye_reference").Optional().Nillable(),
		field.Time("kra_filed_at").Optional().Nillable(),

		field.Bool("delete_status").Default(false).Comment("Soft delete"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (Payslip) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "payment_period"),
		index.Fields("tenant_id", "outlet_id", "payment_period"),
		index.Fields("employee_id"),
		index.Fields("batch_ref"),
	}
}
