package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Timesheet is an employee timesheet period with an approval FSM (legacy
// hrm.attendance.Timesheet). Tenant-scoped; unique per (tenant, employee, period_start,
// period_end). Totals are decimal hours rolled up from TimesheetEntry rows.
type Timesheet struct {
	ent.Schema
}

func (Timesheet) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("approver_id", uuid.UUID{}).Optional().Nillable().Comment("Approving user (SSO shadow)"),
		field.Time("period_start"),
		field.Time("period_end"),
		field.Enum("status").Values("draft", "submitted", "approved", "rejected").Default("draft"),
		field.Time("submission_date").Optional().Nillable(),
		field.Time("approval_date").Optional().Nillable(),
		field.String("rejection_reason").Optional().Nillable(),
		hoursField("total_hours"),
		hoursField("total_overtime_hours"),
		field.String("notes").Optional().Nillable(),
		field.Bool("is_active").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (Timesheet) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id"),
		index.Fields("tenant_id", "employee_id", "period_start", "period_end").Unique(),
	}
}
