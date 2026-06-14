package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ShiftRotation models org-level rotation between WorkShifts over time units (legacy
// hrm.attendance.ShiftRotation). Tenant-scoped. The M2M "shifts" set is stored as a JSON
// array of work_shift UUIDs to keep the schema flat (no join table needed for this CRUD).
type ShiftRotation struct {
	ent.Schema
}

func (ShiftRotation) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.String("title"),
		field.JSON("shift_ids", []uuid.UUID{}).Optional().Comment("WorkShift ids participating in the rotation"),
		field.UUID("current_active_shift_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("last_shift_id", uuid.UUID{}).Optional().Nillable(),
		field.Int("run_duration").Default(2),
		field.String("run_unit").Default("Months"),
		field.Int("break_duration").Default(1),
		field.String("break_unit").Default("Day"),
		field.Time("next_change_date").Optional().Nillable(),
		field.Bool("is_active").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ShiftRotation) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "is_active"),
	}
}
