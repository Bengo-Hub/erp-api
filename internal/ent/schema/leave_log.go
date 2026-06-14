package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// LeaveLog is an audit trail row for a leave request (legacy hrm.leave.LeaveLog).
// Tenant-scoped; one row per create/update/approve/reject/cancel action.
type LeaveLog struct {
	ent.Schema
}

func (LeaveLog) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("leave_request_id", uuid.UUID{}).Comment("FK -> leave_requests.id"),
		field.Enum("action").Values("create", "update", "approve", "reject", "cancel"),
		field.String("description").Optional(),
		field.UUID("user_id", uuid.UUID{}).Optional().Nillable().Comment("Acting user (SSO shadow)"),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (LeaveLog) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "leave_request_id"),
	}
}
