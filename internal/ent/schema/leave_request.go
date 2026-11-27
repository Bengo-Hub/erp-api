package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// LeaveRequest is an employee's leave application with an approval state machine
// (legacy hrm.leave.LeaveRequest). Tenant-scoped. Full approvals engine is Sprint 4;
// until then status transitions are driven directly (pending -> approved|rejected|cancelled).
type LeaveRequest struct {
	ent.Schema
}

func (LeaveRequest) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("category_id", uuid.UUID{}).Comment("FK -> leave_categories.id"),
		field.Time("start_date"),
		field.Time("end_date"),
		field.Bool("start_half_day").Default(false).
			Comment("The leave starts at midday on start_date (on a one-day request: the afternoon off)"),
		field.Bool("end_half_day").Default(false).
			Comment("The leave ends at midday on end_date (on a one-day request: the morning off)"),
		daysField("days_requested"),
		field.String("reason").Optional(),
		field.Enum("status").
			Values("pending", "approved", "rejected", "cancelled").
			Default("pending"),
		field.UUID("approved_by", uuid.UUID{}).Optional().Nillable().Comment("Approver employee id"),
		field.Time("approved_at").Optional().Nillable(),
		field.String("rejection_reason").Optional(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (LeaveRequest) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id"),
		index.Fields("tenant_id", "status"),
	}
}
