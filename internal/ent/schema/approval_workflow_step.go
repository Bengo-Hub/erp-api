package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// approverTypes is the set of approver-resolution strategies a workflow step supports.
// These resolve against the ERP Employee model (NOT the broken legacy `from hrm.models
// import Employee`): department_head/manager are read from the requester's
// HRDetails; role checks the requester's RBAC roles; user is a fixed approver employee.
var approverTypes = []string{
	"user",            // a specific approver (approver_employee_id)
	"role",            // any holder of approver_role
	"department_head", // the requester's department head (HRDetails.head_of_department_id)
	"manager",         // the requester's line manager (HRDetails.reports_to_id)
	"owner",           // the tenant/platform owner
}

// ApprovalWorkflowStep is one sequential sign-off stage of an ApprovalWorkflow, ordered
// by sequence. A request advances to the next step only after the current one is decided.
type ApprovalWorkflowStep struct {
	ent.Schema
}

func (ApprovalWorkflowStep) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant (denormalized for queries)"),
		field.UUID("workflow_id", uuid.UUID{}).Comment("FK to ApprovalWorkflow"),
		field.Int("sequence").Comment("1-based order of this step within the workflow"),
		field.String("name").NotEmpty().Comment("Human label, e.g. 'Manager sign-off'"),
		field.Enum("approver_type").Values(approverTypes...).Default("role"),
		field.String("approver_role").Optional().Comment("RBAC role code when approver_type=role"),
		field.UUID("approver_employee_id", uuid.UUID{}).Optional().Nillable().
			Comment("Fixed approver employee.id when approver_type=user"),
		field.Bool("is_optional").Default(false).Comment("Optional steps may be skipped"),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (ApprovalWorkflowStep) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("workflow", ApprovalWorkflow.Type).
			Ref("steps").
			Field("workflow_id").
			Unique().
			Required(),
	}
}

func (ApprovalWorkflowStep) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("workflow_id", "sequence").Unique(),
		index.Fields("tenant_id"),
	}
}
