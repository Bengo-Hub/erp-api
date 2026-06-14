package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// MetricTarget is a per-employee/period target for a metric (legacy
// hrm.performance.MetricTarget). Tenant-scoped; unique per
// (tenant, employee, metric, period_start, period_end).
type MetricTarget struct {
	ent.Schema
}

func (MetricTarget) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("employee_id", uuid.UUID{}).Comment("FK -> employee.id"),
		field.UUID("metric_id", uuid.UUID{}).Comment("FK -> performance_metrics.id"),
		field.Other("target_value", decimal.Decimal{}).
			SchemaType(map[string]string{"postgres": "numeric(12,2)"}).Default(decimal.Zero),
		field.Time("period_start"),
		field.Time("period_end"),
		field.Bool("is_active").Default(true),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (MetricTarget) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id", "metric_id", "period_start", "period_end").Unique(),
	}
}
