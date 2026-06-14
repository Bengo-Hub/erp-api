package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// WorkShift is a tenant-scoped work-shift definition (legacy hrm.attendance.WorkShift).
// start_time/end_time are stored as "HH:MM" strings (time-of-day) — Postgres-portable and
// parsed by the late-detection logic. Per-day overrides live in WorkShiftSchedule.
type WorkShift struct {
	ent.Schema
}

func (WorkShift) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("outlet_id", uuid.UUID{}).Optional().Nillable(),
		field.String("name"),
		field.String("start_time").Optional().Nillable().Comment("Legacy default start, HH:MM"),
		field.String("end_time").Optional().Nillable().Comment("Legacy default end, HH:MM"),
		field.Int("grace_minutes").Default(0).Comment("Grace period for late arrivals (minutes)"),
		rateField("total_hours_per_week"),
		field.Bool("is_default").Default(false).Comment("Seeded once per tenant (replaces DefaultShiftMiddleware)"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (WorkShift) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "name"),
	}
}
