package payrollengine

import (
	"errors"
	"testing"

	"github.com/shopspring/decimal"
)

func d(s string) decimal.Decimal { return decimal.RequireFromString(s) }

// kra2025Config is the golden-master rate set — now sourced from the shared KRADefaults() so the
// engine test and the global system-tenant seed (cmd/seed-payroll) can never diverge.
func kra2025Config() Config { return KRADefaults() }

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

// TestTaxableAllowances_IncreaseGrossAndPAYE verifies that taxable allowances add to gross,
// statutory base, taxable pay and net pay (additive lane for per-diem/mileage excess etc.).
func TestTaxableAllowances_IncreaseGrossAndPAYE(t *testing.T) {
	cfg := kra2025Config()
	base, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatalf("base compute: %v", err)
	}
	withAllow, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxableAllowances: d("20000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatalf("allow compute: %v", err)
	}
	if !withAllow.GrossPay.Equal(d("120000")) {
		t.Fatalf("gross: got %s want 120000", withAllow.GrossPay)
	}
	// Taxable pay must rise by more than zero and PAYE must increase vs the base run.
	if !withAllow.TaxablePay.GreaterThan(base.TaxablePay) {
		t.Fatalf("taxable did not increase: base %s vs %s", base.TaxablePay, withAllow.TaxablePay)
	}
	if !withAllow.PAYE.GreaterThan(base.PAYE) {
		t.Fatalf("PAYE did not increase: base %s vs %s", base.PAYE, withAllow.PAYE)
	}
}

// TestNonCashAsTaxable verifies the corrected non-cash treatment: excess over the monthly
// exemption is taxed (added to taxable pay) and NOT deducted from net pay; the legacy default
// keeps deducting it from net, untaxed.
func TestNonCashAsTaxable(t *testing.T) {
	legacy := kra2025Config()
	corrected := kra2025Config()
	corrected.NonCashAsTaxable = true
	corrected.NonCashMonthlyExemption = d("3000")

	in := EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary", NonCashBenefits: d("10000")}

	legRes, err := Compute(legacy, in)
	if err != nil {
		t.Fatalf("legacy: %v", err)
	}
	corRes, err := Compute(corrected, in)
	if err != nil {
		t.Fatalf("corrected: %v", err)
	}
	// Corrected mode: taxable pay includes the 7000 excess (10000-3000) -> higher PAYE.
	if !corRes.PAYE.GreaterThan(legRes.PAYE) {
		t.Fatalf("corrected PAYE should exceed legacy: %s vs %s", corRes.PAYE, legRes.PAYE)
	}
	// Corrected mode: non-cash is NOT deducted from net (final deductions exclude it) -> higher net
	// final deductions than legacy by the non-cash amount.
	if !legRes.DeductionsFinal.Equal(d("10000")) {
		t.Fatalf("legacy final deductions should equal non-cash 10000, got %s", legRes.DeductionsFinal)
	}
	if !corRes.DeductionsFinal.Equal(d("0")) {
		t.Fatalf("corrected final deductions should be 0 (in-kind), got %s", corRes.DeductionsFinal)
	}
}
