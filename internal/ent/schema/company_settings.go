package schema

import (
	"time"

	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"entgo.io/ent/schema/index"
	"github.com/google/uuid"
)

// CompanySettings is slim per-tenant ERP business config (renamed from the misspelled
// Django "Bussiness"; fixes the "finacial_year_start_month" typo too). It deliberately
// EXCLUDES branding (auth-api is the SoT — read via the branding S2S cache), tax rates
// (the ERP payroll-tax tables own those), and pickup/address/service-type (ordering-service).
type CompanySettings struct {
	ent.Schema
}

func (CompanySettings) Fields() []ent.Field {
	return []ent.Field{
		field.UUID("id", uuid.UUID{}).Default(uuid.New).Immutable(),
		field.UUID("tenant_id", uuid.UUID{}).Unique().Comment("One settings row per tenant"),

		// HR/Ops company attributes (statutory employer identifiers used on payroll docs).
		field.String("legal_name").Optional(),
		field.String("kra_pin").Optional().Comment("Employer KRA PIN (for P9/P10A headers)"),
		field.String("nssf_employer_no").Optional(),
		field.String("shif_employer_no").Optional(),
		field.String("contact_email").Optional(),
		field.String("contact_phone").Optional(),
		field.String("postal_address").Optional(),
		field.String("physical_address").Optional(),

		field.Int("financial_year_start_month").Default(1).Comment("1-12 (Jan=1); fixes the legacy typo"),
		field.String("default_currency").Default("KES"),
		field.String("timezone").Default("Africa/Nairobi"),

		// Display formats for HR/payroll documents + the erp-ui. Stored as moment-style tokens
		// (e.g. DD/MM/YYYY, HH:mm) so the frontend can apply them directly. String fields with a
		// SQL DEFAULT apply cleanly via online additive auto-migrate (per memory rules).
		field.String("date_format").Default("DD/MM/YYYY").Comment("Moment-style date token, e.g. DD/MM/YYYY"),
		field.String("time_format").Default("HH:mm").Comment("Moment-style time token, e.g. HH:mm / hh:mm A"),

		field.Time("created_at").Default(time.Now).Immutable(),
		field.Time("updated_at").Default(time.Now).UpdateDefault(time.Now),
	}
}

func (CompanySettings) Indexes() []ent.Index {
	return []ent.Index{
		index.Fields("tenant_id").Unique(),
	}
}
