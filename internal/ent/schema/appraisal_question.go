package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AppraisalQuestion is a question within a template (legacy hrm.appraisals.AppraisalQuestion).
type AppraisalQuestion struct {
	ent.Schema
}

func (AppraisalQuestion) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("template_id", uuid.UUID{}).Comment("FK -> appraisal_templates.id"),
		field.String("question_text"),
		field.Enum("question_type").Values("text", "rating", "multiple_choice", "yes_no"),
		field.Bool("is_required").Default(true),
		field.Int("order").Default(0),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (AppraisalQuestion) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "template_id"),
	}
}
