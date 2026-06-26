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

// daysField builds a decimal column for leave/work day quantities (numeric(7,2)) —
// entitlements, balances, days requested/taken. Decimal (never float) per gaps §2.1.
func daysField(name string) ent.Field {
	return field.Other(name, decimal.Decimal{}).
		SchemaType(map[string]string{"postgres": "numeric(7,2)"}).
		Default(decimal.Zero)
}

// hoursField builds a decimal column for worked/overtime hours (numeric(8,2)) —
// attendance records and timesheets. Decimal (never float).
func hoursField(name string) ent.Field {
	return field.Other(name, decimal.Decimal{}).
		SchemaType(map[string]string{"postgres": "numeric(8,2)"}).
		Default(decimal.Zero)
}

// distanceField builds a decimal column for travel distance/km (numeric(10,2)) — used by
// mileage expense routes. Decimal (never float) per gaps §2.1.
func distanceField(name string) ent.Field {
	return field.Other(name, decimal.Decimal{}).
		SchemaType(map[string]string{"postgres": "numeric(10,2)"}).
		Default(decimal.Zero)
}

// ratingFieldOptional builds a nullable 0-5 rating decimal column (numeric(3,1)) used by
// appraisals/performance reviews. Decimal (never float) per gaps §2.1.
func ratingFieldOptional(name string) ent.Field {
	return field.Other(name, decimal.Decimal{}).
		SchemaType(map[string]string{"postgres": "numeric(3,1)"}).
		Optional().
		Nillable()
}
