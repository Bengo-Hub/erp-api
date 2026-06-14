package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// StaffShiftOverride is a date-specific exception to the roster schedule (legacy
// shift_planner_models.StaffShiftOverride). Tenant-scoped; unique per (tenant, employee,
// date). Manager-created overrides auto-approve; staff self-submissions start pending.
type StaffShiftOverride struct {
	ent.Schema
}

func (StaffShiftOverride) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("outlet_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.Time("date"),
		field.Enum("override_type").Values("off_duty", "manual_shift", "half_day"),
		field.String("start_time").Optional().Nillable().Comment("HH:MM; required for manual_shift/half_day"),
		field.String("end_time").Optional().Nillable().Comment("HH:MM; required for manual_shift/half_day"),
		field.String("reason").Optional().Nillable(),
		field.Enum("status").Values("pending", "approved", "rejected").Default("approved"),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.UUID("approved_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (StaffShiftOverride) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id", "date").Unique(),
		index.Fields("tenant_id", "status"),
	}
}
