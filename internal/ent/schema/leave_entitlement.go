package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// LeaveEntitlement is an employee's entitled days for a category/year (legacy
// hrm.leave.LeaveEntitlement). Tenant-scoped; unique per (tenant, employee, category, year).
type LeaveEntitlement struct {
	ent.Schema
}

func (LeaveEntitlement) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("category_id", uuid.UUID{}).Comment("FK -> leave_categories.id"),
		daysField("days_entitled"),
		field.Int("year"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (LeaveEntitlement) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id", "category_id", "year").Unique(),
	}
}
