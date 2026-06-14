package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ApprovalRequest is a live approval-workflow instance bound to a specific HR/Ops object
// (leave request, appraisal, payroll batch, ...). Created when an object is submitted for
// approval and a matching active ApprovalWorkflow with steps exists. Replaces the Django
// GenericForeignKey with a typed (module, object_id) pair (gaps §4).
type ApprovalRequest struct {
	ent.Schema
}

func (ApprovalRequest) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant — REQUIRED for isolation"),
		field.Enum("module").Values(approvalModules...),
		field.UUID("object_id", uuid.UUID{}).Comment("ID of the HR/Ops object being approved"),
		field.String("object_reference").Optional().Comment("Reference for display (e.g. leave ref)"),
		field.UUID("workflow_id", uuid.UUID{}).Optional().Nillable().Comment("Workflow that generated this request"),
		field.UUID("requester_employee_id", uuid.UUID{}).Optional().Nillable().
			Comment("Subject employee — used for manager/department_head resolution"),
		field.Enum("status").
			Values("pending", "approved", "rejected", "cancelled").
			Default("pending"),
		field.Int("current_sequence").Default(1).Comment("Sequence of the step awaiting action"),
		field.UUID("submitted_by", uuid.UUID{}).Optional().Nillable().Comment("Acting user id"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
		field.Time("decided_at").Optional().Nillable().Comment("When the request reached a terminal state"),
	}
}

func (ApprovalRequest) Edges() []ent.Edge {
	return []ent.Edge{
		edge.To("actions", ApprovalStepAction.Type),
	}
}

func (ApprovalRequest) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "module", "object_id"),
		index.Fields("tenant_id", "status"),
	}
}
