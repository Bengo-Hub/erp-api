package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Goal is an employee goal (or a reusable template) with progress 0-100 (legacy
// hrm.appraisals.Goal). Tenant-scoped.
type Goal struct {
	ent.Schema
}

func (Goal) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		// employee_id is nil for reusable library templates (is_template=true); set for an
		// employee's own goal.
		field.UUID("employee_id", uuid.UUID{}).Optional().Nillable().Comment("FK -> employee.id (nil for library templates)"),
		field.String("title"),
		field.String("description").Optional(),
		field.Time("start_date").Optional().Nillable(),
		field.Time("end_date").Optional().Nillable(),
		field.Enum("status").Values("not_started", "in_progress", "completed", "cancelled").Default("not_started"),
		field.Int("progress").Default(0).Comment("0-100"),
		field.Bool("is_template").Default(false),
		// Metadata holds goal attributes without their own column: category and weight.
		field.JSON("metadata", map[string]any{}).Optional(),
		field.UUID("created_by", uuid.UUID{}).Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (Goal) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "employee_id"),
	}
}
