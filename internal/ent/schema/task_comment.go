package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// TaskComment is a discussion note on a Task. Tenant-scoped.
type TaskComment struct {
	ent.Schema
}

func (TaskComment) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("task_id", uuid.UUID{}).Comment("FK to Task"),
		field.UUID("author_user_id", uuid.UUID{}).Optional().Nillable().Comment("Acting user id"),
		field.Text("body").NotEmpty(),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (TaskComment) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("task", Task.Type).
			Ref("comments").
			Field("task_id").
			Unique().
			Required(),
	}
}

func (TaskComment) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("task_id"),
		index.Fields("tenant_id"),
	}
}
