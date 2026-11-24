package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Advance is a salary advance (legacy hrm.payroll.Advances).
type Advance struct {
	ent.Schema
}

func (Advance) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("approver_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("repay_option_id", uuid.UUID{}).Optional().Nillable(),

		field.Bool("approved").Default(false),
		field.JSON("metadata", map[string]any{}).Optional().Comment("reason: the reason given for the advance"),
		field.Time("issue_date").Optional().Nillable(),
		field.Time("prev_payment_date").Optional().Nillable(),
		field.Time("next_payment_date").Optional().Nillable(),
		moneyField("amount_issued"),
		moneyField("amount_repaid"),
		field.Bool("is_active").Default(false),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (Advance) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("employee_id"),
		index.Fields("employee_id", "is_active"),
	}
}
