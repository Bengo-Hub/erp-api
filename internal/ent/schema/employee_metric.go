package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// EmployeeMetric is an employee's recorded metric value (legacy
// hrm.performance.EmployeeMetric). Tenant-scoped; unique per (tenant, employee, metric,
// date_recorded). numeric_value is the decimal projection of value for numeric types.
type EmployeeMetric struct {
	ent.Schema
}

func (EmployeeMetric) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("metric_id", uuid.UUID{}).Comment("FK -> performance_metrics.id"),
		field.String("value").Optional(),
		field.Other("numeric_value", decimal.Decimal{}).
			SchemaType(map[string]string{"postgres": "numeric(12,2)"}).Optional().Nillable(),
		field.Time("date_recorded"),
		field.Time("period_start").Optional().Nillable(),
		field.Time("period_end").Optional().Nillable(),
		field.String("notes").Optional(),
		field.UUID("recorded_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (EmployeeMetric) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id", "metric_id", "date_recorded").Unique(),
	}
}
