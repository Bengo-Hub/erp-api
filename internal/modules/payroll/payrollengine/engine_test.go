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

// reliefConfig is the golden config with the KRA relief caps switched on (as BuildEngineConfig
// resolves them from the tenant's PayrollRelief rows).
func reliefConfig() Config {
	cfg := kra2025Config()
	cfg.InsuranceReliefRate = d("0.15")
	cfg.InsuranceReliefCap = d("5000")
	cfg.PensionReliefCap = d("30000")
	cfg.MortgageReliefCap = d("30000")
	cfg.DisabilityExemptAmount = d("150000")
	return cfg
}

// TestInsuranceRelief: a 10,000 premium yields a 1,500 credit (15%, under the 5,000 cap) that
// reduces PAYE by exactly 1,500 vs the no-relief baseline; chargeable pay is unchanged.
func TestInsuranceRelief(t *testing.T) {
	base, _ := Compute(kra2025Config(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	res, err := Compute(reliefConfig(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary", InsurancePremium: d("10000")})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if !res.InsuranceRelief.Equal(d("1500")) {
		t.Errorf("insurance relief: got %s want 1500", res.InsuranceRelief)
	}
	if !res.TaxablePay.Equal(base.TaxablePay) {
		t.Errorf("taxable changed: got %s want %s", res.TaxablePay, base.TaxablePay)
	}
	if !base.PAYE.Sub(res.PAYE).Equal(d("1500")) {
		t.Errorf("PAYE delta: got %s want 1500", base.PAYE.Sub(res.PAYE))
	}
}

// TestInsuranceReliefCapped: a large premium caps the credit at 5,000/month.
func TestInsuranceReliefCapped(t *testing.T) {
	res, _ := Compute(reliefConfig(), EmployeeInput{GrossPay: d("300000"), TaxCategory: "primary", InsurancePremium: d("80000")})
	if !res.InsuranceRelief.Equal(d("5000")) {
		t.Errorf("insurance relief cap: got %s want 5000", res.InsuranceRelief)
	}
}

// TestPensionDeductible: pension is a PRE-TAX deduction of min(actual, cap, 30% gross); it reduces
// chargeable pay and therefore PAYE.
func TestPensionDeductible(t *testing.T) {
	base, _ := Compute(kra2025Config(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	res, _ := Compute(reliefConfig(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary", PensionContribution: d("20000")})
	if !res.PensionDeduction.Equal(d("20000")) {
		t.Errorf("pension deduction: got %s want 20000", res.PensionDeduction)
	}
	if !res.TaxablePay.Equal(base.TaxablePay.Sub(d("20000"))) {
		t.Errorf("taxable: got %s want %s", res.TaxablePay, base.TaxablePay.Sub(d("20000")))
	}
	if !res.PAYE.LessThan(base.PAYE) {
		t.Errorf("PAYE not reduced: base %s got %s", base.PAYE, res.PAYE)
	}
}

// TestPensionCapped30Percent: the 30%-of-gross ceiling wins when it's the smallest.
func TestPensionCapped30Percent(t *testing.T) {
	// gross 50,000 => 30% = 15,000 < actual 25,000 and < cap 30,000.
	res, _ := Compute(reliefConfig(), EmployeeInput{GrossPay: d("50000"), TaxCategory: "primary", PensionContribution: d("25000")})
	if !res.PensionDeduction.Equal(d("15000")) {
		t.Errorf("pension 30%% cap: got %s want 15000", res.PensionDeduction)
	}
}

// TestMortgageDeductible: owner-occupier interest is deductible up to the 30,000 cap.
func TestMortgageDeductible(t *testing.T) {
	res, _ := Compute(reliefConfig(), EmployeeInput{GrossPay: d("200000"), TaxCategory: "primary", MortgageInterest: d("40000")})
	if !res.MortgageDeduction.Equal(d("30000")) {
		t.Errorf("mortgage deduction: got %s want 30000 (capped)", res.MortgageDeduction)
	}
}

// TestDisabilityExemption: a PWD certificate exempts the first 150,000 of chargeable pay — a
// 100,000 gross earner ends up with zero PAYE.
func TestDisabilityExemption(t *testing.T) {
	res, _ := Compute(reliefConfig(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary", DisabilityExempt: true})
	if !res.PAYE.Equal(decimal.Zero) {
		t.Errorf("disability PAYE: got %s want 0", res.PAYE)
	}
	if res.DisabilityExemption.LessThanOrEqual(decimal.Zero) {
		t.Errorf("disability exemption not applied: %s", res.DisabilityExemption)
	}
	if !res.TaxablePay.Equal(decimal.Zero) {
		t.Errorf("taxable: got %s want 0", res.TaxablePay)
	}
}

// TestSecondaryNoInsuranceRelief: secondary employees get no reliefs (consumed by the primary job).
func TestSecondaryNoInsuranceRelief(t *testing.T) {
	res, _ := Compute(reliefConfig(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "secondary", InsurancePremium: d("10000")})
	if !res.InsuranceRelief.Equal(decimal.Zero) {
		t.Errorf("secondary insurance relief: got %s want 0", res.InsuranceRelief)
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

// TestSecondaryFlatRate: a secondary employee is taxed at the flat top rate (35%) on the whole
// taxable amount with NO relief, using the dedicated IncomeSecondary table — NOT the primary
// progressive bands. Gross 100k -> taxable 91,430 -> PAYE 32,000.50 (vs primary's 19,812.35).
func TestSecondaryFlatRate(t *testing.T) {
	res, err := Compute(kra2025Config(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "secondary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if !res.PersonalRelief.IsZero() {
		t.Errorf("secondary relief should be 0, got %s", res.PersonalRelief)
	}
	if !res.PAYE.Equal(d("32000.50")) {
		t.Errorf("secondary PAYE: got %s want 32000.50 (35%% of 91,430)", res.PAYE)
	}
	// Must be strictly higher than the primary run (the under-taxing bug we fixed).
	primary, _ := Compute(kra2025Config(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	if !res.PAYE.GreaterThan(primary.PAYE) {
		t.Errorf("secondary PAYE %s should exceed primary %s", res.PAYE, primary.PAYE)
	}
}

// TestSecondaryFallback_NoSecondaryTable: when no IncomeSecondary table is configured, a
// secondary employee falls back to the primary bands with relief suppressed (legacy behaviour).
func TestSecondaryFallback_NoSecondaryTable(t *testing.T) {
	cfg := kra2025Config()
	cfg.IncomeSecondary = nil
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "secondary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	// Primary gross tax on 91,430 minus zero relief = 19,812.35 + 2,400 relief that primary
	// would have applied => 22,212.35 (primary progressive bands, no relief).
	if !res.PAYE.Equal(d("22212.35")) {
		t.Errorf("secondary fallback PAYE: got %s want 22212.35 (primary bands, no relief)", res.PAYE)
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

// TestDisabled_NSSF: a deliberate tenant opt-out (Disabled) skips the component silently even
// with no rates configured — distinct from the fail-loud missing-formula path.
func TestDisabled_NSSF(t *testing.T) {
	cfg := kra2025Config()
	cfg.NSSF = nil
	cfg.Disabled = map[string]bool{CompNSSF: true}
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if !res.NSSFEmployeeTier1.IsZero() || !res.NSSFEmployeeTier2.IsZero() || !res.NSSFEmployer.IsZero() {
		t.Errorf("NSSF should be zero when disabled: t1=%s t2=%s er=%s", res.NSSFEmployeeTier1, res.NSSFEmployeeTier2, res.NSSFEmployer)
	}
	// before-tax now only SHIF (2750) + housing (1500) = 4250; taxable = 95750.
	if !res.DeductionsBeforeTax.Equal(d("4250")) {
		t.Errorf("before_tax: got %s want 4250", res.DeductionsBeforeTax)
	}
	if !res.TaxablePay.Equal(d("95750")) {
		t.Errorf("taxable: got %s want 95750", res.TaxablePay)
	}
}

// TestDisabled_PAYE: disabling PAYE behaves like tax category "none" — taxable pay is still
// reported, no tax charged, and a missing income table is tolerated.
func TestDisabled_PAYE(t *testing.T) {
	cfg := kra2025Config()
	cfg.Income = nil
	cfg.IncomeSecondary = nil
	cfg.Disabled = map[string]bool{CompPAYE: true}
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if !res.PAYE.IsZero() || !res.PersonalRelief.IsZero() {
		t.Errorf("PAYE/relief should be zero when disabled: paye=%s relief=%s", res.PAYE, res.PersonalRelief)
	}
	if !res.TaxablePay.Equal(d("91430")) {
		t.Errorf("taxable: got %s want 91430", res.TaxablePay)
	}
	if !res.GrossPayAfterTax.Equal(res.TaxablePay) {
		t.Errorf("gross after tax %s should equal taxable %s", res.GrossPayAfterTax, res.TaxablePay)
	}
	// net = gross - before-tax statutory only (8570)
	if !res.NetPay.Equal(d("91430")) {
		t.Errorf("net: got %s want 91430", res.NetPay)
	}
}

// TestDisabled_SHIF: disabling health covers both SHIF and legacy NHIF with neither configured.
func TestDisabled_SHIF(t *testing.T) {
	cfg := kra2025Config()
	cfg.SHIF = nil
	cfg.NHIF = nil
	cfg.Disabled = map[string]bool{CompSHIF: true, CompNHIF: true}
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if !res.SHIFOrNHIF.IsZero() {
		t.Errorf("SHIF should be zero when disabled, got %s", res.SHIFOrNHIF)
	}
	// before-tax = NSSF 4320 + housing 1500 = 5820
	if !res.DeductionsBeforeTax.Equal(d("5820")) {
		t.Errorf("before_tax: got %s want 5820", res.DeductionsBeforeTax)
	}
}

// TestDisabled_Housing: housing levy opt-out with no rates configured.
func TestDisabled_Housing(t *testing.T) {
	cfg := kra2025Config()
	cfg.HousingLevy = nil
	cfg.Disabled = map[string]bool{CompHousingLevy: true}
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if !res.HousingLevy.IsZero() {
		t.Errorf("housing should be zero when disabled, got %s", res.HousingLevy)
	}
}

// TestDisabled_All: with every statutory component off, net pay equals gross (no recoverables).
func TestDisabled_All(t *testing.T) {
	cfg := Config{
		Disabled: map[string]bool{
			CompPAYE: true, CompNSSF: true, CompSHIF: true, CompNHIF: true,
			CompHousingLevy: true, CompNITA: true,
		},
	}
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	if !res.NetPay.Equal(d("100000")) {
		t.Errorf("net: got %s want 100000 (gross, everything disabled)", res.NetPay)
	}
	if !res.NITAEmployer.IsZero() {
		t.Errorf("NITA should be zero when disabled, got %s", res.NITAEmployer)
	}
}

// TestNITA_EmployerOnly: the NITA levy is charged to the employer and never touches
// employee deductions or net pay.
func TestNITA_EmployerOnly(t *testing.T) {
	withNita := kra2025Config()
	without := kra2025Config()
	without.NITA = nil

	in := EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"}
	a, err := Compute(withNita, in)
	if err != nil {
		t.Fatalf("with NITA: %v", err)
	}
	b, err := Compute(without, in)
	if err != nil {
		t.Fatalf("without NITA: %v", err)
	}
	if !a.NITAEmployer.Equal(d("50")) {
		t.Errorf("NITA employer: got %s want 50", a.NITAEmployer)
	}
	if !b.NITAEmployer.IsZero() {
		t.Errorf("NITA should be zero when unconfigured, got %s", b.NITAEmployer)
	}
	if !a.NetPay.Equal(b.NetPay) {
		t.Errorf("NITA must not change net pay: %s vs %s", a.NetPay, b.NetPay)
	}
}

// TestNSSFYear4_Limits verifies the Year-4 rate set seeded by cmd/seed-payroll (effective
// Feb 2026): tiers 9,000/108,000 @6%, max 540 + 5,940 = 6,480 per side.
func TestNSSFYear4_Limits(t *testing.T) {
	rates := NSSFYear4()
	res, err := CalculateNSSF(rates, d("120000")) // above the UEL -> capped
	if err != nil {
		t.Fatalf("nssf: %v", err)
	}
	if !res.Tier1Employee.Equal(d("540")) {
		t.Errorf("tier1: got %s want 540", res.Tier1Employee)
	}
	if !res.Tier2Employee.Equal(d("5940")) {
		t.Errorf("tier2: got %s want 5940", res.Tier2Employee)
	}
	if !res.TotalEmployer.Equal(d("6480")) {
		t.Errorf("employer: got %s want 6480", res.TotalEmployer)
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
