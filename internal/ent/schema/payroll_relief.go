package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PayrollRelief is a tenant-scoped tax relief (legacy Relief). Repealed reliefs are
// is_active=false (SHIF/Housing relief repeals, Dec 2024).
type PayrollRelief struct {
	ent.Schema
}

func (PayrollRelief) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),

		field.String("type").Comment("Personal | Deductible"),
		field.String("title").NotEmpty(),
		field.Bool("actual_amount").Default(true),
		moneyField("fixed_limit"),
		rateField("percentage"),
		field.String("percent_of").Optional().Nillable().Comment("Actual | Basic | Basic_benefits | ..."),
		field.Bool("is_active").Default(false),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (PayrollRelief) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "type", "is_active"),
	}
}
