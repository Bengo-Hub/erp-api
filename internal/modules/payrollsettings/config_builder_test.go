package payrollsettings

import "testing"

// TestDefaultEmployerPercentage verifies the employer-side fallback used when a statutory
// formula has no explicit PayrollSplitRatio row: NSSF + Housing Levy are employer-matched
// (100%), everything else (SHIF/NHIF/PAYE) is employee-only (0%). This is what makes employer
// contributions appear on the muster roll / GL / P9 even when split rows were never seeded.
func TestDefaultEmployerPercentage(t *testing.T) {
	cases := map[string]string{
		"social_security_fund": "1",
		"housing_levy":         "1",
		"shif":                 "0",
		"nhif":                 "0",
		"primary":              "0",
		"secondary":            "0",
		"":                     "0",
	}
	for category, want := range cases {
		if got := defaultEmployerPercentage(category).String(); got != want {
			t.Errorf("defaultEmployerPercentage(%q) = %s, want %s", category, got, want)
		}
	}
}
