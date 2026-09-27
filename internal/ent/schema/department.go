package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Department is reference data (core.Departments, ERD §3). Self-referential hierarchy.
type Department struct {
	ent.Schema
}

func (Department) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).
			Optional().
			Nillable(),
		field.String("code").Optional(),
		field.String("title").NotEmpty(),
		field.UUID("parent_department_id", uuid.UUID{}).
			Optional().
			Nillable(),
		// cost_center_id links the department to a treasury cost center: payroll cost not
		// allocated to a project is attributed here, so department budgets see their salaries.
		field.UUID("cost_center_id", uuid.UUID{}).
			Optional().
			Nillable().
			Comment("treasury cost center for this department's unallocated payroll cost"),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
	}
}

func (Department) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("code"),
	}
}
