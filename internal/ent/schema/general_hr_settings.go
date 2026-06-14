package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// GeneralHRSettings is PER-TENANT payroll config (legacy GeneralHRSettings was a global
// singleton — now tenant-scoped, gaps §2 isolation). One row per tenant.
type GeneralHRSettings struct {
	ent.Schema
}

func (GeneralHRSettings) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Unique().Comment("Owning tenant (one settings row per tenant)"),

		rateField("overtime_normal_days"),
		rateField("overtime_non_working_days"),
		rateField("overtime_holidays"),
		field.String("partial_months").Default("prorate_calendar").
			Comment("prorate_calendar | prorate_working_days | no_proration"),
		field.String("round_off_currency").Default("KES"),
		moneyField("round_off_amount"),
		field.Bool("allow_backwards_payroll").Default(false),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (GeneralHRSettings) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id").Unique(),
	}
}
