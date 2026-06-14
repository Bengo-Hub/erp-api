package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// LeaveBalance is the computed entitled/taken/remaining position for an employee per
// category/year (legacy hrm.leave.LeaveBalance). Tenant-scoped; the accrual cron and the
// approve path keep it in sync. days_remaining = days_entitled - days_taken (+ carryover).
type LeaveBalance struct {
	ent.Schema
}

func (LeaveBalance) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("category_id", uuid.UUID{}).Comment("FK -> leave_categories.id"),
		field.Int("year"),
		daysField("days_entitled"),
		daysField("days_taken"),
		daysField("days_remaining"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (LeaveBalance) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id", "category_id", "year").Unique(),
	}
}
