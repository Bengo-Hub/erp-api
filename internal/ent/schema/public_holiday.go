package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// PublicHoliday is a Kenyan public holiday (national or county-specific). Made
// tenant-scoped per the sprint spec: legacy uniq(date,county) -> uniq(tenant,date,county)
// so each tenant maintains its own holiday calendar (fixes the global-table isolation gap).
type PublicHoliday struct {
	ent.Schema
}

func (PublicHoliday) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.String("name"),
		field.Time("date"),
		field.Bool("is_national").Default(true),
		field.String("county").Optional().Nillable().Comment("County when not national"),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (PublicHoliday) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "date"),
		index.Fields("tenant_id", "date", "county").Unique(),
	}
}
