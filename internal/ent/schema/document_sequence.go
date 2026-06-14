package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// DocumentSequence holds per-tenant, per-doc-type atomic counters + format config for
// branded HR/Ops document numbering (payslip, payroll_report, ...). Mirrors the
// inventory-api/treasury-api DocumentSequence; the service increments via optimistic CAS.
type DocumentSequence struct {
	ent.Schema
}

func (DocumentSequence) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Tenant this sequence belongs to"),
		field.String("doc_type").NotEmpty().Comment("payslip, payroll_report, p9, p10a, ..."),
		field.String("prefix").Optional().Comment("Number prefix, e.g. PAY, RPT"),
		field.String("separator").Default("-"),
		field.String("date_format").Optional().Comment("YYYYMMDD, YYMMDD, MMYY, YYYY — empty = no date"),
		field.Int("padding").Default(6),
		field.String("reset_freq").Default("never").Comment("daily, monthly, yearly, never"),
		field.Int64("current_val").Default(0),
		field.Time("last_reset").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (DocumentSequence) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "doc_type").Unique(),
	}
}
