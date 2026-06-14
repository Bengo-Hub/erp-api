package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ReviewMetric is a metric scored within a PerformanceReview (legacy
// hrm.performance.ReviewMetric). Tenant-scoped; unique per (tenant, review, metric).
// rating is decimal 0-5.
type ReviewMetric struct {
	ent.Schema
}

func (ReviewMetric) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("review_id", uuid.UUID{}).Comment("FK -> performance_reviews.id"),
		field.UUID("metric_id", uuid.UUID{}).Comment("FK -> performance_metrics.id"),
		field.String("value").Optional(),
		ratingFieldOptional("rating"),
		field.String("comments").Optional(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ReviewMetric) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "review_id", "metric_id").Unique(),
	}
}
