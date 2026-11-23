package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// quantityField is a decimal production quantity (numeric(14,3)).
func quantityField(name string) ent.Field {
	return field.Other(name, decimal.Decimal{}).
		SchemaType(map[string]string{"postgres": "numeric(14,3)"}).
		Default(decimal.Zero)
}

// PieceOutput is what an employee produced on a day at a piece rate. Rejected units (from
// QC) are not paid. Approved output becomes an earning in the payroll run of its month and is
// marked paid with the payslip.
type PieceOutput struct {
	ent.Schema
}

func (PieceOutput) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("piece_rate_id", uuid.UUID{}).Comment("FK -> piece_rates.id"),
		field.Time("date"),
		quantityField("quantity"),
		quantityField("rejected_quantity"),
		// rate is the snapshot of the piece rate when recorded; amount is
		// (quantity - rejected_quantity) x rate.
		moneyField("rate"),
		moneyField("amount"),
		field.String("currency"),
		field.Text("note").Optional(),
		field.Enum("status").Values("pending", "approved", "rejected", "paid").Default("pending"),
		field.UUID("recorded_by", uuid.UUID{}).Optional().Nillable(),
		field.UUID("reviewed_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("reviewed_at").Optional().Nillable(),
		field.UUID("payslip_id", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (PieceOutput) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "date"),
		index.Fields("tenant_id", "employee_id", "date"),
		index.Fields("tenant_id", "status"),
	}
}
