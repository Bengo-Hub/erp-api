package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// PerformanceMetric is a metric definition assignable to employees (legacy
// hrm.performance.PerformanceMetric). Tenant-scoped. min/max/target are decimal.
type PerformanceMetric struct {
	ent.Schema
}

func metricBound(name string) ent.Field {
	return field.Other(name, decimal.Decimal{}).
		SchemaType(map[string]string{"postgres": "numeric(12,2)"}).
		Optional().Nillable()
}

func (PerformanceMetric) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("category_id", uuid.UUID{}).Comment("FK -> metric_categories.id"),
		field.String("name"),
		field.String("description").Optional(),
		field.Enum("metric_type").Values("numeric", "percentage", "boolean", "rating", "text"),
		field.String("unit").Optional(),
		metricBound("min_value"),
		metricBound("max_value"),
		metricBound("target_value"),
		field.Bool("is_active").Default(true),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (PerformanceMetric) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "category_id"),
	}
}
