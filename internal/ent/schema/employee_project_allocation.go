package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// EmployeeProjectAllocation records that an employee/consultant works on a projects-service
// project and the share of their time/pay attributed to it. This is how employees & consultants
// are tied to projects: a consultant on multiple projects has one row per project (percentages
// should sum to <=100). Used to split/attribute salary cost across projects and to drive the
// erp.payroll.project_allocations side-car for per-project cost reporting. Each row may have its
// own start/end so allocations track varying project completion dates.
type EmployeeProjectAllocation struct {
	ent.Schema
}

func (EmployeeProjectAllocation) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id (employee or consultant)"),
		field.UUID("project_id", uuid.UUID{}).Comment("projects-service project id"),
		field.String("project_name").Optional().Comment("Denormalised project name for display"),
		field.UUID("cost_center_id", uuid.UUID{}).Optional().Nillable(),
		// allocation_percent: share of the employee's pay attributed to this project (0-100).
		moneyField("allocation_percent"),
		// fixed_amount: optional flat per-period amount instead of a percentage (e.g. milestone fee).
		field.Float("fixed_amount").Optional().Nillable(),
		field.Time("start_date").Optional().Nillable(),
		field.Time("end_date").Optional().Nillable().Comment("Project completion / allocation end"),
		field.Bool("is_active").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmployeeProjectAllocation) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id"),
		index.Fields("tenant_id", "project_id"),
	}
}
