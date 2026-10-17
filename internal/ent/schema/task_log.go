package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TaskLog is an audit trail entry for a Task (status changes, assignment, progress).
// Tenant-scoped.
type TaskLog struct {
	ent.Schema
}

func (TaskLog) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("task_id", uuid.UUID{}).Comment("FK to Task"),
		field.String("action").NotEmpty().Comment("created | status_changed | assigned | progress | comment"),
		field.String("description").Optional(),
		field.UUID("user_id", uuid.UUID{}).Optional().Nillable().Comment("Acting user id"),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (TaskLog) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("task", Task.Type).
			Ref("logs").
			Field("task_id").
			Unique().
			Required(),
	}
}

func (TaskLog) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("task_id"),
		index.Fields("tenant_id"),
	}
}
