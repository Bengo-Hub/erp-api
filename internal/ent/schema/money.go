package schema

import (
	"entgo.io/ent"
	"entgo.io/ent/schema/field"
	"github.com/shopspring/decimal"
)

// moneyField builds a fixed-precision decimal money column (numeric(18,4)) backed by
// shopspring/decimal — NEVER float (gaps-and-bugs §2.1). 18,4 is the single internal
// precision used across the payroll engine and persisted statutory/net amounts.
//
// All payroll/HRM money columns MUST go through this helper so the Postgres type, Go
// type, and default are uniform across the schema. It returns a fully-built field
// (NOT NULL, default 0); for nullable money use moneyFieldOptional.
func moneyField(name string) ent.Field {
	return field.Other(name, decimal.Decimal{}).
		SchemaType(map[string]string{"postgres": "numeric(18,4)"}).
		Default(decimal.Zero)
}

// moneyFieldOptional is the nullable variant of moneyField (numeric(18,4), NULL allowed).
func moneyFieldOptional(name string) ent.Field {
	return field.Other(name, decimal.Decimal{}).
		SchemaType(map[string]string{"postgres": "numeric(18,4)"}).
		Optional().
		Nillable()
}

// rateField builds a percentage/rate decimal column (numeric(10,4)) — used for tax
// rates, split ratios and overtime multipliers. Same decimal guarantees as moneyField.
func rateField(name string) ent.Field {
	return field.Other(name, decimal.Decimal{}).
		SchemaType(map[string]string{"postgres": "numeric(10,4)"}).
		Default(decimal.Zero)
}
