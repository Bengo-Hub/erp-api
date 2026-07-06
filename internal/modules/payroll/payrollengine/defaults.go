package payrollengine

import "github.com/shopspring/decimal"

func mustDec(s string) decimal.Decimal { return decimal.RequireFromString(s) }

// KRADefaults returns the canonical Kenyan statutory rate set used as BOTH the golden-master
// test oracle AND the global system-tenant seed (cmd/seed-payroll). Keeping a single source of
// truth means the seeded national defaults and the verified engine test can never diverge.
//
// Rates (Finance Act 2023 PAYE; NSSF/SHIF/Housing as effective for the golden master):
//   - PAYE bands 10/25/30/32.5/35, monthly personal relief 2,400
//   - NSSF tiers 0–8,000 and 8,000–72,000 @ 6% (employee + employer matched 100%)
//   - SHIF 2.75% of gross (employee only)
//   - Housing Levy 1.5% (employee + employer matched)
func KRADefaults() Config {
	return Config{
		Income: &FormulaRates{
			Bands: []Band{
				{From: mustDec("0"), To: mustDec("24000"), Rate: mustDec("0.10")},
				{From: mustDec("24000"), To: mustDec("32333"), Rate: mustDec("0.25")},
				{From: mustDec("32333"), To: mustDec("500000"), Rate: mustDec("0.30")},
				{From: mustDec("500000"), To: mustDec("799999"), Rate: mustDec("0.325")},
				{From: mustDec("799999"), To: Inf, Rate: mustDec("0.35")},
			},
			PersonalRelief: mustDec("2400"),
		},
		// Secondary employment: taxed at the top marginal rate (35%) on the whole amount, no
		// relief (the primary employer already used the lower bands + relief). Mirrors the
		// Wingubox "P.A.Y.E. Kenya (Secondary Employee)" table.
		IncomeSecondary: &FormulaRates{
			Bands: []Band{{From: mustDec("0"), To: Inf, Rate: mustDec("0.35")}},
		},
		NSSF: &FormulaRates{
			Bands: []Band{
				{From: mustDec("0"), To: mustDec("8000"), Rate: mustDec("0.06")},
				{From: mustDec("8000"), To: mustDec("72000"), Rate: mustDec("0.06")},
			},
			EmployeePercentage: mustDec("1"),
			EmployerPercentage: mustDec("1"),
		},
		SHIF: &FormulaRates{
			Bands:              []Band{{From: mustDec("0"), To: Inf, Rate: mustDec("0.0275")}},
			EmployeePercentage: mustDec("1"),
		},
		HousingLevy: &FormulaRates{
			Bands:              []Band{{From: mustDec("0"), To: Inf, Rate: mustDec("0.015")}},
			EmployeePercentage: mustDec("1"),
			EmployerPercentage: mustDec("1"),
		},
		// NITA industrial training levy: flat KES 50/employee/month, employer-only.
		// Never affects employee deductions or net pay (golden master unchanged).
		NITA: &FormulaRates{
			Bands:              []Band{{From: mustDec("0"), To: Inf, Amount: mustDec("50")}},
			EmployerPercentage: mustDec("1"),
		},
		RecoverAdvances: true,
	}
}

// NSSFYear4 returns the NSSF Act 2013 Third Schedule YEAR 4 rate set, effective 1 Feb 2026:
// Tier I up to KES 9,000 and Tier II 9,001–108,000, 6% employee matched 100% by the employer
// (max KES 6,480 per side). Seeded by cmd/seed-payroll as the current NSSF formula; the
// KRADefaults NSSF above stays on the earlier limits because it is the golden-master oracle.
func NSSFYear4() *FormulaRates {
	return &FormulaRates{
		Bands: []Band{
			{From: mustDec("0"), To: mustDec("9000"), Rate: mustDec("0.06")},
			{From: mustDec("9000"), To: mustDec("108000"), Rate: mustDec("0.06")},
		},
		EmployeePercentage: mustDec("1"),
		EmployerPercentage: mustDec("1"),
	}
}
