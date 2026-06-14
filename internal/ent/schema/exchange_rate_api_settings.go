package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// ExchangeRateAPISettings configures the FX provider per tenant (legacy
// integrations.ExchangeRateAPISettings). The provider API key is NOT stored here as
// ciphertext (fixes gaps §1.1/§1.2 — the Django version kept a Fernet ciphertext in the DB);
// instead it holds a secret REFERENCE (env var name) resolved from the secret store at fetch.
type ExchangeRateAPISettings struct {
	ent.Schema
}

func (ExchangeRateAPISettings) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Unique().Comment("One settings row per tenant"),
		field.String("provider").Default("exchangerate-api"),
		field.String("api_key_ref").Optional().
			Comment("Env-var name holding the provider key (secret store), NOT the key itself"),
		field.String("base_currency").Default("KES"),
		field.Bool("is_active").Default(false),
		field.Time("last_fetched_at").Optional().Nillable(),
		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (ExchangeRateAPISettings) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id").Unique(),
	}
}
