package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// WorkSite is a geo-fenced place where staff clock in: a circle (center plus radius) or a
// polygon ring in GeoJSON [lng, lat] order, checked with httpware/geo.
type WorkSite struct {
	ent.Schema
}

func (WorkSite) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("outlet_id", uuid.UUID{}).Optional().Nillable(),
		field.String("name"),
		field.Float("center_lat").Default(0),
		field.Float("center_lng").Default(0),
		field.Float("radius_m").Default(100),
		field.JSON("ring", [][]float64{}).Optional(),
		field.JSON("holes", [][][]float64{}).Optional(),
		field.Bool("active").Default(true),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (WorkSite) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("tenant_id", "active"),
	}
}
