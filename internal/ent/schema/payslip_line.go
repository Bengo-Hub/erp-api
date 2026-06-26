package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PayslipLine is a single itemised line on a generated payslip (one earning/benefit/
// deduction/statutory/employer-contribution). The payslip row keeps the aggregate totals
// for fast queries; these lines drive the rich payslip PDF, the Muster Roll's dynamic
// per-component columns, the 3-column Payroll Summary and P9 — none of which a flat
// aggregate payslip can produce. Written by the engine at process time.
type PayslipLine struct {
	ent.Schema
}

func (PayslipLine) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (denormalised for scoping)"),
		field.UUID("payslip_id", uuid.UUID{}).Comment("FK -> payslip.id"),
		field.UUID("component_id", uuid.UUID{}).Optional().Nillable().Comment("Source PayrollComponent, if any"),

		// section groups the line for rendering: earning_cash | benefit_noncash |
		// deduction_before_tax | tax | relief | deduction_after_tax | employer_contribution.
		field.String("section"),
		field.String("code").Optional().Comment("Stable code, e.g. basic|paye|nssf_t1|shif|housing_levy|loan"),
		field.String("label"),

		// cash_amount is what affects net pay; taxable_amount is the value used for PAYE
		// (== cash for normal cash items; the fringe "[Effective: X]" value for non-cash benefits).
		moneyField("cash_amount"),
		moneyField("taxable_amount"),
		moneyField("employer_amount"), // employer side (NSSF employer, FBT employer)

		field.Bool("non_cash").Default(false),
		field.Bool("taxable").Default(true),

		// Per-unit earnings (Daily Wages, Overtime): qty x rate, with the unit for the label.
		daysField("quantity"),
		moneyField("rate"),
		field.String("unit").Optional().Comment("days | hours | pieces"),

		field.String("deduction_phase").Optional().Comment("before_tax | after_tax | after_paye | final"),
		field.Int("sort_order").Default(0),

		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (PayslipLine) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("payslip_id"),
		index.Fields("tenant_id", "section"),
	}
}
