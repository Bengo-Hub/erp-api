package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TimesheetEntry is a daily entry within a Timesheet (legacy
// hrm.attendance.TimesheetEntry). Tenant-scoped; unique per (tenant, timesheet, date).
type TimesheetEntry struct {
	ent.Schema
}

func (TimesheetEntry) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("timesheet_id", uuid.UUID{}).Comment("FK -> timesheets.id"),
		field.UUID("project_id", uuid.UUID{}).Optional().Nillable(),
		field.Time("date"),
		field.String("task_description").Optional(),
		hoursField("regular_hours"),
		hoursField("overtime_hours"),
		hoursField("break_hours"),
		field.String("notes").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (TimesheetEntry) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "timesheet_id", "date").Unique(),
	}
}
