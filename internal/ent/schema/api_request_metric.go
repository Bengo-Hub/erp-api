package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ApiRequestMetric records per-request performance metrics (core.ApiRequestMetric, ERD §3).
// Prometheus is the primary telemetry path; this table backs the UI performance dashboard.
type ApiRequestMetric struct {
	ent.Schema
}

func (ApiRequestMetric) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).
			Optional().
			Nillable(),
		field.String("method").NotEmpty(),
		field.String("path").NotEmpty(),
		field.Int("status_code"),
		field.Float("duration_ms"),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
	}
}

func (ApiRequestMetric) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("created_at"),
		index.Fields("path"),
		index.Fields("status_code"),
	}
}
