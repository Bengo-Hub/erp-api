package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ShiftAssignment assigns an employee to a roster for an active date window (legacy
// shift_planner_models.ShiftAssignment). Tenant-scoped. end_date NULL = open-ended.
type ShiftAssignment struct {
	ent.Schema
}

func (ShiftAssignment) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("roster_id", uuid.UUID{}).Comment("FK -> shift_rosters.id"),
		field.Time("start_date"),
		field.Time("end_date").Optional().Nillable().Comment("Open-ended if NULL"),
		field.Bool("is_active").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ShiftAssignment) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id", "is_active"),
		index.Fields("tenant_id", "roster_id"),
	}
}
