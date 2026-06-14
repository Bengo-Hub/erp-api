package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// LoanType is a tenant-scoped loan product definition (legacy payroll_settings.Loans).
type LoanType struct {
	ent.Schema
}

func (LoanType) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),

		field.String("wb_code").Optional().Nillable(),
		field.String("account_code").Optional().Nillable(),
		field.String("title").NotEmpty(),
		field.Bool("is_active").Default(false),
		rateField("round_off"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (LoanType) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
	}
}
