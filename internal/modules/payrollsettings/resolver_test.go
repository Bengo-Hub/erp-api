package payrollsettings

import (
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

var (
	sysT    = uuid.MustParse("00000000-0000-0000-0000-0000000005ff")
	tenantA = uuid.MustParse("aaaaaaaa-0000-0000-0000-000000000001")
)

func day(y int, m time.Month, d int) *time.Time {
	t := time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
	return &t
}

func formula(tenant uuid.UUID, ftype, cat string, current bool, from, to *time.Time) *ent.PayrollFormula {
	return &ent.PayrollFormula{ID: uuid.New(), TenantID: tenant, Type: ftype, Category: cat, Title: ftype + "/" + cat,
		IsCurrent: current, EffectiveFrom: from, EffectiveTo: to}
}

// A tenant with no formulas of its own sees every platform formula (the empty Formulas tab bug).
func TestMergeFormulas_InheritsPlatform(t *testing.T) {
	paye := formula(sysT, "income", "primary", true, day(2023, 7, 1), nil)
	nssf := formula(sysT, "deduction", "social_security_fund", true, day(2026, 2, 1), nil)
	got := mergeFormulas([]*ent.PayrollFormula{paye, nssf}, tenantA, sysT)
	if len(got) != 2 {
		t.Fatalf("want 2 inherited formulas, got %d", len(got))
	}
	for _, g := range got {
		if g.Source != SourcePlatform || g.OverridesID != nil {
			t.Errorf("%s: want platform source without override, got %s", g.Formula.Title, g.Source)
		}
	}
}

// A tenant's own version replaces the platform row of the same (type, category) only.
func TestMergeFormulas_TenantOverride(t *testing.T) {
	platPAYE := formula(sysT, "income", "primary", true, day(2023, 7, 1), nil)
	platSHIF := formula(sysT, "deduction", "shif", true, day(2024, 10, 1), nil)
	ownPAYE := formula(tenantA, "income", "primary", true, day(2025, 1, 1), nil)
	other := formula(uuid.New(), "income", "primary", true, day(2025, 1, 1), nil) // another tenant: never visible
	got := mergeFormulas([]*ent.PayrollFormula{ownPAYE, platPAYE, platSHIF, other}, tenantA, sysT)
	if len(got) != 2 {
		t.Fatalf("want own PAYE + platform SHIF, got %d rows", len(got))
	}
	if got[0].Formula.ID != ownPAYE.ID || got[0].Source != SourceTenant || got[0].OverridesID == nil || *got[0].OverridesID != platPAYE.ID {
		t.Errorf("own PAYE should be a tenant row overriding the platform PAYE: %+v", got[0])
	}
	if got[1].Formula.ID != platSHIF.ID || got[1].Source != SourcePlatform {
		t.Errorf("SHIF should stay inherited: %+v", got[1])
	}
}

// The platform tenant sees its rows as platform rows.
func TestMergeFormulas_PlatformTenant(t *testing.T) {
	paye := formula(sysT, "income", "primary", true, day(2023, 7, 1), nil)
	got := mergeFormulas([]*ent.PayrollFormula{paye}, sysT, sysT)
	if len(got) != 1 || got[0].Source != SourcePlatform {
		t.Fatalf("platform tenant: %+v", got)
	}
}

// Inherited vs overridden resolution for a run.
func TestResolveEffective_InheritAndOverride(t *testing.T) {
	period := *day(2026, 3, 1)
	plat := formula(sysT, "income", "primary", true, day(2023, 7, 1), nil)
	if got := resolveEffective(nil, []*ent.PayrollFormula{plat}, period); got != plat {
		t.Fatal("tenant without a version must inherit the platform formula")
	}
	own := formula(tenantA, "income", "primary", true, day(2025, 1, 1), nil)
	if got := resolveEffective([]*ent.PayrollFormula{own}, []*ent.PayrollFormula{plat}, period); got != own {
		t.Fatal("tenant version in force must win over the platform formula")
	}
	// The tenant version starts later than the period: the platform row applies to that month.
	future := formula(tenantA, "income", "primary", true, day(2026, 7, 1), nil)
	if got := resolveEffective([]*ent.PayrollFormula{future}, []*ent.PayrollFormula{plat}, period); got != plat {
		t.Fatal("a tenant version not yet in force must not apply; the platform formula covers the month")
	}
}

// A platform edit (new current version) reaches tenants without their own version, and earlier
// months keep the version in force then (effective date change mid year).
func TestResolveEffective_PlatformVersionMidYear(t *testing.T) {
	old := formula(sysT, "deduction", "social_security_fund", false, day(2024, 2, 1), day(2026, 1, 31))
	cur := formula(sysT, "deduction", "social_security_fund", true, day(2026, 2, 1), nil)
	rows := []*ent.PayrollFormula{cur, old}
	if got := resolveEffective(nil, rows, *day(2026, 1, 1)); got != old {
		t.Error("January 2026 must use the retired limits")
	}
	if got := resolveEffective(nil, rows, *day(2026, 2, 1)); got != cur {
		t.Error("February 2026 must use the new limits")
	}
	if got := resolveEffective(nil, rows, *day(2026, 11, 1)); got != cur {
		t.Error("later months must use the current version")
	}
	// A tenant override applies only to the tenant that made it.
	own := formula(tenantA, "deduction", "social_security_fund", true, day(2025, 1, 1), nil)
	if got := resolveEffective([]*ent.PayrollFormula{own}, rows, *day(2026, 11, 1)); got != own {
		t.Error("overriding tenant keeps its own version after the platform edit")
	}
}

// A superseded row without an end date never covers later months.
func TestCovers_SupersededOpenEnded(t *testing.T) {
	old := formula(tenantA, "income", "primary", false, day(2023, 7, 1), nil)
	if covers(old, *day(2026, 1, 1)) {
		t.Fatal("a superseded open-ended row must not cover later months")
	}
	if !covers(formula(tenantA, "income", "primary", true, day(2023, 7, 1), nil), *day(2026, 1, 1)) {
		t.Fatal("a current row covers every month from its start")
	}
	if covers(formula(tenantA, "income", "primary", true, nil, nil), *day(2026, 1, 1)) {
		t.Fatal("a row without a start date is not date-covering (it is the always-current fallback)")
	}
	cur := formula(tenantA, "income", "primary", true, nil, nil)
	if got := resolveEffective([]*ent.PayrollFormula{cur}, nil, *day(2026, 1, 1)); got != cur {
		t.Fatal("a current row without dates still resolves as the fallback")
	}
}

func TestResolveEffective_NothingConfigured(t *testing.T) {
	if got := resolveEffective(nil, nil, *day(2026, 1, 1)); got != nil {
		t.Fatal("no rows must resolve to nil so the run fails loud")
	}
}

func relief(tenant uuid.UUID, title string, limit, pct string, active bool) *ent.PayrollRelief {
	return &ent.PayrollRelief{ID: uuid.New(), TenantID: tenant, Type: "Deductible", Title: title,
		FixedLimit: decimal.RequireFromString(limit), Percentage: decimal.RequireFromString(pct), IsActive: active,
		ActualAmount: true, UpdatedAt: time.Now()}
}

// Platform reliefs are inherited and statutory ones (personal, insurance) are on by default.
func TestMergeReliefs_Inherited(t *testing.T) {
	rows := []*ent.PayrollRelief{
		relief(sysT, "Personal Relief", "2400", "0", true),
		relief(sysT, "Insurance Relief", "5000", "15", true),
		relief(sysT, "Pension Relief", "30000", "100", true),
	}
	got := mergeReliefs(rows, tenantA, sysT)
	if len(got) != 3 {
		t.Fatalf("want 3 reliefs, got %d", len(got))
	}
	if !got[0].Statutory || !got[1].Statutory || got[2].Statutory {
		t.Errorf("statutory reliefs must sort first: %+v", got)
	}
	for _, g := range got {
		if !g.IsActive || g.Source != SourcePlatform {
			t.Errorf("%s: want active platform relief", g.Title)
		}
	}
}

// A tenant activation record (no amounts) switches a relief off but keeps platform values; a
// legacy UI code row ("insurance_relief") counts as the same relief.
func TestMergeReliefs_ActivationAndLegacyCode(t *testing.T) {
	plat := relief(sysT, "Insurance Relief", "5000", "15", true)
	legacy := relief(tenantA, "insurance_relief", "0", "0", false)
	got := mergeReliefs([]*ent.PayrollRelief{plat, legacy}, tenantA, sysT)
	if len(got) != 1 {
		t.Fatalf("legacy row must merge onto the platform relief, got %d rows", len(got))
	}
	r := got[0]
	if r.IsActive || r.Source != SourceTenant || !r.FixedLimit.Equal(decimal.NewFromInt(5000)) || r.Title != "Insurance Relief" {
		t.Errorf("want switched off with platform values, got %+v", r)
	}
	// A tenant row with its own amounts replaces the values.
	own := relief(tenantA, "Insurance Relief", "6000", "15", true)
	got = mergeReliefs([]*ent.PayrollRelief{plat, own}, tenantA, sysT)
	if !got[0].FixedLimit.Equal(decimal.NewFromInt(6000)) || got[0].PlatformID == nil {
		t.Errorf("tenant values must apply: %+v", got[0])
	}
}

func TestReliefKey(t *testing.T) {
	cases := map[string]string{
		"personal_relief":           reliefPersonal,
		"Personal Relief":           reliefPersonal,
		"housing_relief":            reliefHousing,
		"Affordable Housing Relief": reliefHousing,
		"disability_relief":         reliefDisability,
		"mortgage_relief":           reliefMortgage,
	}
	for in, want := range cases {
		if got := ReliefKey(in); got != want {
			t.Errorf("ReliefKey(%q) = %q, want %q", in, got, want)
		}
	}
}

// Reliefs drive the engine caps; personal relief switched off removes it from PAYE.
func TestApplyReliefs(t *testing.T) {
	cfg := payrollengine.KRADefaults()
	reliefs := []ResolvedRelief{
		{Key: reliefPersonal, IsActive: true, FixedLimit: decimal.NewFromInt(2400)},
		{Key: reliefInsurance, IsActive: true, FixedLimit: decimal.NewFromInt(5000), Percentage: decimal.NewFromInt(15)},
		{Key: reliefPension, IsActive: false, FixedLimit: decimal.NewFromInt(30000)},
	}
	applyReliefs(reliefs, &cfg)
	if !cfg.InsuranceReliefCap.Equal(decimal.NewFromInt(5000)) || !cfg.InsuranceReliefRate.Equal(decimal.RequireFromString("0.15")) {
		t.Errorf("insurance relief caps: %s %s", cfg.InsuranceReliefCap, cfg.InsuranceReliefRate)
	}
	if !cfg.PensionReliefCap.IsZero() {
		t.Error("an inactive relief must not set its cap")
	}
	if !cfg.Income.PersonalRelief.Equal(decimal.NewFromInt(2400)) {
		t.Error("active personal relief keeps the formula's relief")
	}
	off := payrollengine.KRADefaults()
	applyReliefs([]ResolvedRelief{{Key: reliefPersonal, IsActive: false}}, &off)
	if !off.Income.PersonalRelief.IsZero() {
		t.Error("personal relief switched off must remove it")
	}
	if !payrollengine.KRADefaults().Income.PersonalRelief.Equal(decimal.NewFromInt(2400)) {
		t.Error("switching relief off must not mutate the shared defaults")
	}
}

// The golden master still holds when the config comes through the relief resolver with the
// platform reliefs (personal on; insurance relief only matters with a premium).
func TestGoldenMaster_ThroughResolvedReliefs(t *testing.T) {
	cfg := payrollengine.KRADefaults()
	applyReliefs([]ResolvedRelief{
		{Key: reliefPersonal, IsActive: true},
		{Key: reliefInsurance, IsActive: true, FixedLimit: decimal.NewFromInt(5000), Percentage: decimal.NewFromInt(15)},
	}, &cfg)
	res, err := payrollengine.Compute(cfg, payrollengine.EmployeeInput{GrossPay: decimal.NewFromInt(100000), TaxCategory: "primary"})
	if err != nil {
		t.Fatal(err)
	}
	if got := res.NetPay.StringFixed(2); got != "71617.65" {
		t.Fatalf("golden master net pay = %s, want 71617.65", got)
	}
}
