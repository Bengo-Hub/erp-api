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
// governs. It replaces the Django GenericForeignKey (content_type_id+object_id) with a
// typed module enum (gaps §4). Decomposed workflow types (purchase_order|expense|invoice|
// requisition) are intentionally ABSENT — those domains live in other services.
var approvalModules = []string{
	"payroll",
	"leave_request",
	"contract",
	"appraisal",
	"performance_review",
	"recruitment_offer",
	"general",
}

// ApprovalWorkflow defines, per tenant and module, a named multi-step approval chain.
// It is tenant-scoped (the Django version was global — gaps §4). When a domain object is
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
