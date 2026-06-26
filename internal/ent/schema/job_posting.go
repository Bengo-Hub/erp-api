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
		// Public careers portal: slug (URL ref), visibility, employment type, number of openings and
		// an application deadline. All nullable / defaulted → online additive-migration safe.
		field.String("slug").Optional().Nillable().Comment("URL slug for the public careers portal"),
		field.Bool("is_public").Default(false).Comment("Listed on the public careers portal"),
		field.String("employment_type").Optional().Nillable().Comment("full_time | part_time | contract | internship | temporary"),
		field.Int("num_positions").Default(1),
		field.Time("application_deadline").Optional().Nillable(),
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
