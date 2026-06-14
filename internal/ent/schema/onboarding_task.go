package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// OnboardingTask is a checklist item within an EmployeeOnboarding (legacy
// hrm.recruitment.OnboardingTask). Tenant-scoped; seeded from a default checklist on start.
type OnboardingTask struct {
	ent.Schema
}

func (OnboardingTask) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("onboarding_id", uuid.UUID{}).Comment("FK -> employee_onboardings.id"),
		field.Enum("category").Values("IT", "HR", "Training", "Other").Default("Other"),
		field.String("title"),
		field.Int("order").Default(0),
		field.Bool("is_done").Default(false),
		field.Time("done_at").Optional().Nillable(),
		field.UUID("assigned_to", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (OnboardingTask) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "onboarding_id"),
	}
}
