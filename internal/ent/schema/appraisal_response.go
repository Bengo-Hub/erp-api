package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AppraisalResponse is an answer to a question within an appraisal (legacy
// hrm.appraisals.AppraisalResponse). Tenant-scoped. rating is decimal 0-5.
type AppraisalResponse struct {
	ent.Schema
}

func (AppraisalResponse) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("appraisal_id", uuid.UUID{}).Comment("FK -> appraisals.id"),
		field.UUID("question_id", uuid.UUID{}).Comment("FK -> appraisal_questions.id"),
		field.String("response").Optional(),
		ratingFieldOptional("rating"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (AppraisalResponse) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "appraisal_id"),
	}
}
