package payrollengine

import (
	"errors"
	"testing"

	"github.com/shopspring/decimal"
)

func d(s string) decimal.Decimal { return decimal.RequireFromString(s) }

// kra2025Config builds the Feb-2025 KRA national rate set used by the golden-master.
func kra2025Config() Config {
	return Config{
		Income: &FormulaRates{
			Bands: []Band{
				{From: d("0"), To: d("24000"), Rate: d("0.10")},
				{From: d("24000"), To: d("32333"), Rate: d("0.25")},
				{From: d("32333"), To: d("500000"), Rate: d("0.30")},
				{From: d("500000"), To: d("799999"), Rate: d("0.325")},
				{From: d("799999"), To: Inf, Rate: d("0.35")},
			},
			PersonalRelief: d("2400"),
		},
		NSSF: &FormulaRates{
			Bands: []Band{
				{From: d("0"), To: d("8000"), Rate: d("0.06")},
				{From: d("8000"), To: d("72000"), Rate: d("0.06")},
			},
			EmployeePercentage: d("1"),
			EmployerPercentage: d("1"),
		},
		SHIF: &FormulaRates{
			Bands:              []Band{{From: d("0"), To: Inf, Rate: d("0.0275")}},
			EmployeePercentage: d("1"),
		},
		HousingLevy: &FormulaRates{
			Bands:              []Band{{From: d("0"), To: Inf, Rate: d("0.015")}},
			EmployeePercentage: d("1"),
			EmployerPercentage: d("1"),
		},
		RecoverAdvances: true,
	}
}

func TestGoldenMaster_Gross100k(t *testing.T) {
	res, err := Compute(kra2025Config(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	checks := map[string]struct{ got, want decimal.Decimal }{
		"nssf_t1":    {res.NSSFEmployeeTier1, d("480")},
		"nssf_t2":    {res.NSSFEmployeeTier2, d("3840")},
		"shif":       {res.SHIFOrNHIF, d("2750")},
		"housing":    {res.HousingLevy, d("1500")},
		"taxable":    {res.TaxablePay, d("91430")},
		"paye":       {res.PAYE, d("19812.35")},
		"relief":     {res.PersonalRelief, d("2400")},
		"net":        {res.NetPay, d("71617.65")},
		"before_tax": {res.DeductionsBeforeTax, d("8570")},
	}
	for name, c := range checks {
		if !c.got.Equal(c.want) {
			t.Errorf("%s: got %s want %s", name, c.got, c.want)
		}
	}
}

// TestFailLoud_MissingNSSF: a missing required statutory formula must abort, never zero.
func TestFailLoud_MissingNSSF(t *testing.T) {
	cfg := kra2025Config()
	cfg.NSSF = nil
	_, err := Compute(cfg, EmployeeInput{GrossPay: d("50000"), TaxCategory: "primary"})
	if !errors.Is(err, ErrFormulaNotConfigured) {
		t.Fatalf("expected ErrFormulaNotConfigured, got %v", err)
	}
}

// TestFailLoud_MissingIncome: missing PAYE bands aborts.
func TestFailLoud_MissingIncome(t *testing.T) {
	cfg := kra2025Config()
	cfg.Income = nil
	_, err := Compute(cfg, EmployeeInput{GrossPay: d("50000"), TaxCategory: "primary"})
	if !errors.Is(err, ErrFormulaNotConfigured) {
		t.Fatalf("expected ErrFormulaNotConfigured, got %v", err)
	}
}

// TestLowIncome_NoNegativePAYE: relief exceeding gross tax floors PAYE at 0.
func TestLowIncome_NoNegativePAYE(t *testing.T) {
	res, err := Compute(kra2025Config(), EmployeeInput{GrossPay: d("15000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if res.PAYE.LessThan(decimal.Zero) {
		t.Errorf("PAYE negative: %s", res.PAYE)
	}
}

// TestRecoverablesCappedAtOutstanding: never recover more than outstanding.
func TestRecoverablesCappedAtOutstanding(t *testing.T) {
	in := EmployeeInput{
		GrossPay:    d("100000"),
		TaxCategory: "primary",
		Loans:       []Recoverable{{Installment: d("5000"), Outstanding: d("1200")}},
	}
	res, err := Compute(kra2025Config(), in)
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if !res.DeductionsAfterPAYE.Equal(d("1200")) {
		t.Errorf("loan recovery: got %s want 1200 (capped)", res.DeductionsAfterPAYE)
	}
}

// TestSecondaryNoRelief: secondary employees get no personal relief.
func TestSecondaryNoRelief(t *testing.T) {
	res, err := Compute(kra2025Config(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "secondary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if !res.PersonalRelief.IsZero() {
		t.Errorf("secondary should have 0 relief, got %s", res.PersonalRelief)
	}
}
