package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ApprovalStepAction is one step instance within an ApprovalRequest — the per-step audit
// record capturing who approved/rejected/escalated, when, and any comment.
type ApprovalStepAction struct {
	ent.Schema
}

func (ApprovalStepAction) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("request_id", uuid.UUID{}).Comment("FK to ApprovalRequest"),
		field.Int("sequence").Comment("Matches the originating ApprovalWorkflowStep sequence"),
		field.String("name").Optional().Comment("Step label snapshot"),
		field.Enum("approver_type").Values(approverTypes...).Default("role"),
		field.String("approver_role").Optional().Comment("Role required to act on this step"),
		field.UUID("approver_employee_id", uuid.UUID{}).Optional().Nillable().
			Comment("Resolved approver employee id (manager/department_head/user)"),
		field.Enum("status").
			Values("pending", "approved", "rejected", "skipped", "escalated").
			Default("pending"),
		field.UUID("acted_by", uuid.UUID{}).Optional().Nillable().Comment("Acting user id"),
		field.Time("acted_at").Optional().Nillable(),
		field.Text("comment").Optional(),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (ApprovalStepAction) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("request", ApprovalRequest.Type).
			Ref("actions").
			Field("request_id").
			Unique().
			Required(),
	}
}

func (ApprovalStepAction) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("request_id", "sequence"),
		index.Fields("tenant_id"),
	}
}
