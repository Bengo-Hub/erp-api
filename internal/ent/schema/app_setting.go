package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// AppSetting is a generic key/value tenant-scoped settings store (core.AppSettings, ERD §3).
type AppSetting struct {
	ent.Schema
}

func (AppSetting) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).
			Default(uuid.New).
			Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).
			Optional().
			Nillable().
			Comment("NULL = system-wide setting"),
		field.String("app_key").
			NotEmpty(),
		field.Text("value").
			Optional(),
		field.Time("created_at").
			Default(time.Now).
			Immutable(),
		field.Time("updated_at").
			Default(time.Now).
			UpdateDefault(time.Now),
	}
}

func (AppSetting) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id", "app_key").Unique(),
		index.Fields("app_key"),
	}
}
