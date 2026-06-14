package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PayslipAudit is the payslip action trail (legacy PayslipAudit).
type PayslipAudit struct {
	ent.Schema
}

func (PayslipAudit) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("payslip_id", uuid.UUID{}).Comment("FK -> payslip.id"),
		field.UUID("action_by", uuid.UUID{}).Optional().Nillable(),

		field.String("action").Comment("Created | Approved | Rejected | Nulled | Draft | Disbursed"),
		field.Text("remarks").Optional().Nillable(),
		field.Time("action_date").Default(time.Now).Immutable(),
	}
}

func (PayslipAudit) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("payslip_id"),
	}
}
