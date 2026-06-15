package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ExchangeRate is a fetched FX rate (base->quote) for a date (legacy core.ExchangeRate).
// Written by the FX cron. Tenant-optional: NULL tenant_id = platform-wide reference rate.
type ExchangeRate struct {
	ent.Schema
}

func (ExchangeRate) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Optional().Nillable().Comment("NULL = platform-wide reference"),
		field.String("base_currency").Default("KES"),
		field.String("quote_currency").NotEmpty(),
		moneyField("rate"),
		field.Time("rate_date"),
		field.String("source").Default("exchangerate-api"),
		field.Time("created_at").Default(time.Now).Immutable(),
	}
}

func (ExchangeRate) Indexes() []ent.Index {
	return []ent.Index{
		// Tenant-scoped uniqueness: each tenant (and the platform, tenant_id NULL) may hold its own
		// rate per currency-pair/date. (Was missing tenant_id — a multi-tenant FX bug.)
		index.Fields("tenant_id", "base_currency", "quote_currency", "rate_date").Unique(),
		index.Fields("tenant_id"),
	}
}
