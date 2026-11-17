package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/dialect/entsql"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TimesheetEntry is the time an employee logged on one date of a Timesheet (legacy
// hrm.attendance.TimesheetEntry), per project and, when projects-api logs it, per task. Tenant
// scoped; one row per (tenant, timesheet, date, project, task), which the service keeps for rows
// without a project or task too (Postgres treats NULLs as distinct in the unique index).
type TimesheetEntry struct {
	ent.Schema
}

func (TimesheetEntry) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("timesheet_id", uuid.UUID{}).Comment("FK -> timesheets.id"),
		field.UUID("project_id", uuid.UUID{}).Optional().Nillable(),
		field.UUID("task_id", uuid.UUID{}).Optional().Nillable().
			Comment("projects-api task the time was logged on"),
		field.Bool("billable").Default(false).
			Comment("Billable to the project's client (projects-api decides from the project's billing terms)"),
		field.Time("date"),
		field.String("task_description").Optional(),
		hoursField("regular_hours"),
		hoursField("overtime_hours"),
		hoursField("break_hours"),
		field.String("notes").Optional().Nillable(),
		// The SQL DEFAULT '{}' lets the online migration add the NOT NULL column to existing rows.
		field.JSON("metadata", map[string]any{}).Default(map[string]any{}).
			Annotations(entsql.Default("{}")).
			Comment("billing_ref (uuid) while projects-api bills the entry; billed_invoice_id (uuid) once the invoice is confirmed"),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (TimesheetEntry) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "timesheet_id", "date", "project_id", "task_id").Unique(),
	}
}
