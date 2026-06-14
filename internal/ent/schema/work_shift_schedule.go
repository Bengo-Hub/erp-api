package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// WorkShiftSchedule is a day-wise schedule row for a WorkShift (legacy
// hrm.attendance.WorkShiftSchedule). Unique per (tenant, work_shift, day).
type WorkShiftSchedule struct {
	ent.Schema
}

func (WorkShiftSchedule) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("work_shift_id", uuid.UUID{}).Comment("FK -> work_shifts.id"),
		field.Enum("day").Values("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"),
		field.String("start_time").Comment("HH:MM"),
		field.String("end_time").Comment("HH:MM"),
		rateField("break_hours"),
		field.Bool("is_working_day").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (WorkShiftSchedule) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "work_shift_id", "day").Unique(),
	}
}
