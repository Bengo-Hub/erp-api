package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// JobPosting is a tenant-scoped recruitment posting (legacy hrm.recruitment.JobPosting).
type JobPosting struct {
	ent.Schema
}

func (JobPosting) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.String("title"),
		field.String("description").Optional(),
		field.String("department").Optional().Nillable(),
		field.String("location").Optional().Nillable(),
		field.Enum("status").Values("draft", "open", "closed", "archived").Default("draft"),
		field.Time("posted_at").Default(time.Now),
		field.Time("closed_at").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (JobPosting) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "status"),
	}
}
