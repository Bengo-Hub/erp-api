package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// approvalModules is the typed set of HR/Ops workflow types the ERP approval engine
// governs. Objects are referenced by a typed module enum
// plus an object id. Decomposed workflow types (purchase_order|expense|invoice|
// requisition) are intentionally ABSENT — those domains live in other services.
var approvalModules = []string{
	"payroll",
	"leave_request",
	"contract",
	"appraisal",
	"performance_review",
	"recruitment_offer",
	"attendance_regularisation",
	"overtime_request",
	"general",
}

// ApprovalWorkflow defines, per tenant and module, a named multi-step approval chain.
// It is tenant-scoped. When a domain object is
// submitted for approval, the active workflow for its module drives the approval steps.
type ApprovalWorkflow struct {
	ent.Schema
}

func (ApprovalWorkflow) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant — REQUIRED for isolation"),
		field.Enum("module").Values(approvalModules...).Comment("HR/Ops object type this workflow governs"),
		field.String("name").NotEmpty(),
		field.String("description").Optional(),
		field.Bool("is_active").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ApprovalWorkflow) Edges() []ent.Edge {
	return []ent.Edge{
		edge.To("steps", ApprovalWorkflowStep.Type),
	}
}

func (ApprovalWorkflow) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "module", "is_active"),
	}
}
