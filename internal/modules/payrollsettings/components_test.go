package payrollsettings

import (
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

func platformComponent(code string) *ent.PayrollComponent {
	it := catalogueByCode[code]
	c := code
	return &ent.PayrollComponent{ID: uuid.New(), TenantID: sysT, WbCode: &c, Title: it.Title, Category: it.Category,
		Statutory: it.Statutory, IsActive: true, Amount: decimal.Zero, Percentage: decimal.Zero}
}

func byCode(rs []ResolvedComponent) map[string]ResolvedComponent {
	m := map[string]ResolvedComponent{}
	for _, r := range rs {
		key := r.Code
		if key == "" {
			key = r.Title
		}
		m[key] = r
	}
	return m
}

// Statutory components are on by default, module-managed ones are on, the rest are opt-in.
func TestMergeComponents_Defaults(t *testing.T) {
	rows := []*ent.PayrollComponent{platformComponent("paye"), platformComponent("loans"), platformComponent("house_allowance")}
	got := byCode(mergeComponents(rows, tenantA, sysT, nil, allStatutoryOn))
	if !got["paye"].Active || got["paye"].Source != SourcePlatform || got["paye"].StatutoryToggle == "" {
		t.Errorf("PAYE must be on, inherited and governed by the statutory toggle: %+v", got["paye"])
	}
	if !got["loans"].Active || got["loans"].ManagedBy != ManagedLoans {
		t.Errorf("loan repayment is module-managed and on: %+v", got["loans"])
	}
	if got["house_allowance"].Active || got["house_allowance"].DefaultActive {
		t.Errorf("house allowance must be opt-in: %+v", got["house_allowance"])
	}
}

// Opt-in on, values customised, statutory toggled off: all through small per-tenant records.
func TestMergeComponents_TenantChoices(t *testing.T) {
	rows := []*ent.PayrollComponent{platformComponent("nssf"), platformComponent("house_allowance"), platformComponent("sacco")}
	on := true
	amt := decimal.NewFromInt(15000)
	choices := map[string]ComponentChoice{
		"house_allowance": {Active: &on, Amount: &amt, Title: "Housing"},
		"sacco":           {Active: &on},
	}
	toggles := allStatutoryOn
	toggles.nssf = false
	got := byCode(mergeComponents(rows, tenantA, sysT, choices, toggles))
	ha := got["house_allowance"]
	if !ha.Active || !ha.Customised || ha.Source != SourceTenant || !ha.Amount.Equal(amt) || ha.Title != "Housing" {
		t.Errorf("customised house allowance: %+v", ha)
	}
	if !got["sacco"].Active || got["sacco"].Customised || got["sacco"].Source != SourcePlatform {
		t.Errorf("SACCO switched on without new values stays a platform row: %+v", got["sacco"])
	}
	if got["nssf"].Active {
		t.Error("NSSF follows the tenant's statutory toggle")
	}
	// Another tenant without choices is unaffected by tenant A's record.
	other := byCode(mergeComponents(rows, uuid.New(), sysT, nil, allStatutoryOn))
	if other["house_allowance"].Active || !other["nssf"].Active {
		t.Error("choices are per tenant")
	}
}

// A platform edit (new amount) reaches every tenant that did not set its own amount.
func TestMergeComponents_PlatformEditReflects(t *testing.T) {
	ha := platformComponent("house_allowance")
	ha.Amount = decimal.NewFromInt(10000)
	on := true
	got := byCode(mergeComponents([]*ent.PayrollComponent{ha}, tenantA, sysT, map[string]ComponentChoice{"house_allowance": {Active: &on}}, allStatutoryOn))
	if !got["house_allowance"].Amount.Equal(decimal.NewFromInt(10000)) {
		t.Error("tenant without its own amount must see the platform amount")
	}
}

// A platform row switched off by the platform owner is off for every tenant, even opted in.
func TestMergeComponents_PlatformRetired(t *testing.T) {
	ha := platformComponent("house_allowance")
	ha.IsActive = false
	on := true
	got := byCode(mergeComponents([]*ent.PayrollComponent{ha}, tenantA, sysT, map[string]ComponentChoice{"house_allowance": {Active: &on}}, allStatutoryOn))
	if got["house_allowance"].Active {
		t.Error("a retired platform component cannot be switched on by a tenant")
	}
}

// The tenant's own component with the same title or code replaces the platform one (no
// duplicates in the list), and other tenants' rows never appear.
func TestMergeComponents_OwnShadowsPlatform(t *testing.T) {
	own := &ent.PayrollComponent{ID: uuid.New(), TenantID: tenantA, Title: "house allowance", Category: CategoryEarnings, IsActive: true}
	rows := []*ent.PayrollComponent{own, platformComponent("house_allowance"), platformComponent("bonus")}
	got := mergeComponents(rows, tenantA, sysT, nil, allStatutoryOn)
	if len(got) != 2 {
		t.Fatalf("want own house allowance + platform bonus, got %d", len(got))
	}
	for _, g := range got {
		if g.Title == "house allowance" && (g.Source != SourceTenant || !g.Active) {
			t.Errorf("own component: %+v", g)
		}
	}
}

// Every catalogue code is unique, statutory codes map to a toggle, and statutory items are on.
func TestPlatformCatalogue(t *testing.T) {
	seen := map[string]bool{}
	for _, it := range PlatformCatalogue() {
		if seen[it.Code] {
			t.Errorf("duplicate code %s", it.Code)
		}
		seen[it.Code] = true
		if it.Statutory {
			if _, ok := statutoryToggleOf[it.Code]; !ok {
				t.Errorf("statutory %s has no toggle", it.Code)
			}
		}
		switch it.Category {
		case CategoryEarnings, CategoryDeductions, CategoryBenefits:
		default:
			t.Errorf("%s: bad category %q", it.Code, it.Category)
		}
	}
	for _, code := range []string{"basic", "paye", "nssf", "shif", "housing_levy", "nita", "helb", "loans", "advances", "sacco", "union_dues", "pension", "overtime", "bonus", "commission", "per_diem"} {
		if !seen[code] {
			t.Errorf("catalogue misses %s", code)
		}
	}
}

func TestComponentChoice_Customised(t *testing.T) {
	on := true
	if (ComponentChoice{Active: &on}).customised() {
		t.Error("on or off alone is not a value customisation")
	}
	zero := decimal.Zero
	if !(ComponentChoice{Amount: &zero}).customised() {
		t.Error("an explicit zero amount is a customisation")
	}
}
