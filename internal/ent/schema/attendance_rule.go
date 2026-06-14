package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AttendanceRule holds priority-ordered late/overtime/absence policies (legacy
// hrm.attendance.AttendanceRule). Tenant-scoped; the highest-priority active rule of a
// given rule_type drives the hours/late computation. Decimal hours/rates throughout.
type AttendanceRule struct {
	ent.Schema
}

func (AttendanceRule) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("branch_id", uuid.UUID{}).Optional().Nillable().Comment("Optional branch/outlet scope"),
		field.UUID("department_id", uuid.UUID{}).Optional().Nillable(),
		field.String("name"),
		field.Enum("rule_type").Values("late_policy", "overtime_policy", "absenteeism_policy", "work_hours_policy", "break_policy", "holiday_policy"),
		field.String("description").Optional().Nillable(),
		field.Bool("is_active").Default(true),
		field.Int("priority").Default(100).Comment("Higher = applied first"),

		// Late policy.
		field.Int("late_threshold_minutes").Default(15),
		field.String("late_penalty_type").Default("warning"),
		rateField("late_penalty_value"),

		// Overtime policy.
		rateField("overtime_threshold_hours"),
		rateField("overtime_rate_multiplier"),
		rateField("max_overtime_hours"),

		// Absenteeism policy.
		field.Int("consecutive_absent_threshold").Default(3),
		field.Int("monthly_absent_threshold").Default(5),
		field.String("absenteeism_action").Default("warning"),

		// Work-hours policy.
		rateField("standard_work_hours"),
		rateField("min_work_hours"),
		rateField("max_work_hours"),

		// Break policy.
		field.Int("break_duration_minutes").Default(60),

		// Holiday policy.
		rateField("holiday_pay_multiplier"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (AttendanceRule) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "rule_type", "is_active"),
		index.Fields("tenant_id", "priority"),
	}
}
