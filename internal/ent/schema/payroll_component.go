package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PayrollComponent is a configurable earning/deduction/benefit line (legacy
// PayrollComponents). Carries deduction phase + priority for engine ordering.
type PayrollComponent struct {
	ent.Schema
}

func (PayrollComponent) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),

		field.String("wb_code").Optional().Nillable(),
		field.String("acc_code").Optional().Nillable(),
		field.String("title").NotEmpty(),
		field.String("category").Optional().Comment("Benefits | Earnings | Deductions"),
		field.Text("description").Optional().Nillable(),
		field.String("mode").Optional().Comment("monthly | weekly | daily | perhour | perday | perpiece | commission"),

		// Default monetary configuration (legacy "Default Payroll Settings"). The amount/percentage
		// is the employee-side default; employer_* carries the employer contribution for split
		// deductions (NSSF/pension). percent_of is the base a percentage applies to. Per-unit
		// earnings (Daily Wages, Overtime) carry unit_type/unit_rate/quantity. All decimal.
		moneyField("amount"),
		rateField("percentage"),
		field.String("percent_of").Optional().Comment("basic | gross | none — base a percentage applies to"),
		moneyField("employer_amount"),
		rateField("employer_percentage"),
		field.String("registration_no").Optional().Nillable().Comment("e.g. insurer/pension scheme registration"),
		field.String("unit_type").Optional().Comment("days | hours | pieces — for per-unit earnings"),
		moneyField("unit_rate"),
		daysField("quantity"),
		field.Time("effective_from").Optional().Nillable(),
		field.Time("effective_to").Optional().Nillable(),

		field.Bool("non_cash").Default(false),
		field.Bool("deduct_after_taxing").Default(false),
		field.UUID("applicable_relief_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("applicable_tax_formula_id", uuid.UUID{}).Optional().Nillable().Comment("BenefitTax id"),
		field.Bool("checkoff").Default(true),
		field.Bool("constant").Default(true),
		field.Bool("statutory").Default(false),
		field.Bool("is_active").Default(true),
		field.String("taxable_status").Optional().Comment("taxable | nontaxable | lowincome | gratuity"),

		field.String("deduction_phase").Default("before_tax").Comment("before_tax | after_tax | after_paye | final"),
		field.Int("deduction_priority").Default(1).Comment("Order within a phase (lower = earlier)"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (PayrollComponent) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "category"),
	}
}
