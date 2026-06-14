package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/edge"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// Permission is a fine-grained erp-api permission (replaces Django auth_permission).
type Permission struct {
	ent.Schema
}

func (Permission) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.String("permission_code").
			NotEmpty().
			Unique().
			Comment("e.g. hrm.employees.add, hrm.payroll.view"),
		field.String("name").
			NotEmpty(),
		field.String("module").
			NotEmpty().
			Comment("e.g. employees, payroll, leave, attendance, approvals"),
		field.String("action").
			NotEmpty().
			Comment("add | view | change | delete | manage"),
		field.String("resource").
			Optional(),
		field.Text("description").
			Optional(),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
	}
}

func (Permission) Edges() []ent.Edge {
	return []ent.Edge{
		edge.From("roles", Role.Type).Ref("permissions").Through("role_permissions", RolePermission.Type),
	}
}

func (Permission) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("permission_code").Unique(),
		index.Fields("module"),
		index.Fields("action"),
		index.Fields("module", "action"),
	}
}
