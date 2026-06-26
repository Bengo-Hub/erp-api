package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Application is a candidate's application to a posting with a hiring-pipeline FSM
// (legacy hrm.recruitment.Application). Tenant-scoped. Valid transitions are enforced in
// the service: applied->screening->interview->offered->hired, with rejected reachable from
// any non-terminal stage.
type Application struct {
	ent.Schema
}

func (Application) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("job_id", uuid.UUID{}).Comment("FK -> job_postings.id"),
		field.UUID("candidate_id", uuid.UUID{}).Comment("FK -> candidates.id"),
		field.Enum("status").
			Values("applied", "screening", "interview", "offered", "hired", "rejected").
			Default("applied"),
		field.Time("applied_at").Default(time.Now),
		field.String("notes").Optional().Nillable(),
		// Applicant-provided motivation + how they reached us (public careers portal sets these).
		field.Text("cover_letter").Optional().Nillable(),
		field.String("source").Optional().Nillable().Comment("careers_portal | referral | direct | agency"),
		field.UUID("hired_employee_id", uuid.UUID{}).Optional().Nillable().
			Comment("Employee created on hire (links recruitment -> onboarding)"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (Application) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "job_id", "status"),
		index.Fields("tenant_id", "candidate_id"),
	}
}
