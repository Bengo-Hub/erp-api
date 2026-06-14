package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Task is an ERP-internal job/work-item tracker (legacy task_management.Task) — distinct
// from projects-service projects/tenders (data-ownership: ERP owns only this internal
// tracker). Tenant-scoped, assignable, with status + priority and a comment/log trail.
type Task struct {
	ent.Schema
}

func (Task) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant — REQUIRED for isolation"),
		field.String("title").NotEmpty(),
		field.Text("description").Optional(),
		field.Enum("status").
			Values("todo", "in_progress", "blocked", "done", "cancelled").
			Default("todo"),
		field.Enum("priority").
			Values("low", "medium", "high", "urgent").
			Default("medium"),
		field.UUID("assignee_employee_id", uuid.UUID{}).Optional().Nillable().Comment("Assigned employee.id"),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable().Comment("Acting user id"),
		field.String("category").Optional().Comment("Free-form grouping / task type"),
		field.Int("progress").Default(0).Comment("0-100 percent complete"),
		field.Time("due_date").Optional().Nillable(),
		field.Time("completed_at").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (Task) Edges() []ent.Edge {
	return []ent.Edge{
		edge.To("comments", TaskComment.Type),
		edge.To("logs", TaskLog.Type),
	}
}

func (Task) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "status"),
		index.Fields("tenant_id", "assignee_employee_id"),
	}
}
