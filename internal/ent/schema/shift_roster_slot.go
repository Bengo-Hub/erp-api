package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ShiftRosterSlot is an employee's scheduled hours for one cycle_day of a roster (legacy
// shift_planner_models.ShiftRosterSlot). Tenant-scoped; unique per
// (tenant, roster, employee, cycle_day). Times are "HH:MM" strings.
type ShiftRosterSlot struct {
	ent.Schema
}

func (ShiftRosterSlot) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("roster_id", uuid.UUID{}).Comment("FK -> shift_rosters.id"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.Int("cycle_day").Comment("1-based position within the roster cycle"),
		field.String("start_time").Optional().Nillable().Comment("HH:MM"),
		field.String("end_time").Optional().Nillable().Comment("HH:MM"),
		field.Bool("is_off_day").Default(false),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (ShiftRosterSlot) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "roster_id", "cycle_day"),
		index.Fields("tenant_id", "roster_id", "employee_id", "cycle_day").Unique(),
	}
}
