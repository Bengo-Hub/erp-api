package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// MileageRoute is a single leg of a mileage expense claim (claim_type=mileage). A mileage
// claim is made up of one or more routes; the claim amount is the sum of route amounts where
// amount = distance × rate. Lines give the claim a reimbursable paper trail (from/to, km, rate)
// that mirrors the Wingubox mileage form.
type MileageRoute struct {
	ent.Schema
}

func (MileageRoute) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Comment("Owning tenant"),
		field.UUID("expense_claim_id", uuid.UUID{}).Comment("FK -> expense_claim.id"),

		field.Time("route_date").Optional().Nillable().Comment("Date the trip was made"),
		field.String("from_location").Optional().Comment("Origin"),
		field.String("to_location").Optional().Comment("Destination"),
		// distance (km) × rate (per km) = amount. All decimals, never float (gaps §2.1).
		distanceField("distance"),
		rateField("rate"),
		moneyField("amount"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (MileageRoute) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id"),
		index.Fields("expense_claim_id"),
	}
}
