package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/dialect/entsql"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PayrollFormula is the ERP-OWNED, tenant-scoped, effective-dated statutory rate table
// (legacy hrm.payroll_settings.Formulas). Replaces global rates + the disabled save()
// invariant (gaps §2.3): a DB partial unique index enforces ONE current formula per
// (tenant, type, category). Rates are NEVER read from treasury (revamp-plan §5).
type PayrollFormula struct {
	ent.Schema
}

func (PayrollFormula) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant; default-tenant rows are the inherited KRA national defaults"),

		field.String("type").Comment("income | deduction | earning | fbt | levy | relief_allowance"),
		field.String("category").Optional().Comment("primary | secondary | social_security_fund | shif | nhif | housing_levy | fbt"),
		field.String("title").NotEmpty(),
		field.String("unit").Default("KES"),

		field.Time("effective_from").Optional().Nillable(),
		field.Time("effective_to").Optional().Nillable(),

		rateField("upper_limit"),
		moneyField("upper_limit_amount"),
		rateField("upper_limit_percentage"),
		moneyField("personal_relief"),
		field.Bool("relief_carry_forward").Default(false),
		moneyField("min_taxable_income"),
		field.Bool("progressive").Default(false),

		field.UUID("component_id", uuid.UUID{}).Optional().Nillable().Comment("Linked PayrollComponent (deduction)"),

		field.String("version").Default("1.0"),
		field.String("regulatory_source").Optional().Nillable().Comment("e.g. Finance Act 2025"),
		field.Text("notes").Optional().Nillable(),
		field.JSON("deduction_order", []DeductionPhase{}).Optional().
			Comment("Ordered deduction phases: before_tax -> after_tax -> after_paye -> final"),

		field.Bool("is_current").Default(false),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (PayrollFormula) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "type", "category"),
		index.Fields("tenant_id", "type", "category", "effective_from"),
		// ONE current formula per (tenant, type, category) — partial unique (gaps §2.3).
		index.Fields("tenant_id", "type", "category").
			Unique().
			StorageKey("uq_payroll_formula_current").
			Annotations(entsql.IndexWhere("is_current = true")),
	}
}

// DeductionPhase is one phase in a formula's deduction ordering (engine phasing).
type DeductionPhase struct {
	Phase      string   `json:"phase"`
	Components []string `json:"components"`
}
