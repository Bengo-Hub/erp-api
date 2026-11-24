package payrollsettings

import (
	"context"
	"database/sql"
	"os"
	"strings"
	"testing"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// testClient runs against Postgres when ERP_TEST_DATABASE_URL is set: a throwaway schema with the
// current ent schema, dropped when the test ends.
func testClient(t *testing.T) *ent.Client {
	t.Helper()
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_pset_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	if _, err := admin.Exec("CREATE SCHEMA " + schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = admin.Exec("DROP SCHEMA " + schema + " CASCADE"); _ = admin.Close() })
	sep := "?"
	if strings.Contains(url, "?") {
		sep = "&"
	}
	db, err := sql.Open("pgx", url+sep+"search_path="+schema)
	if err != nil {
		t.Fatal(err)
	}
	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, db)))
	t.Cleanup(func() { _ = client.Close() })
	if err := client.Schema.Create(context.Background()); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return client
}

// seedPlatform writes the KRA defaults as platform formulas, the platform reliefs and catalogue.
func seedPlatform(t *testing.T, ctx context.Context, svc *Service) {
	t.Helper()
	def := payrollengine.KRADefaults()
	from := day(2024, 1, 1)
	add := func(ftype, cat string, r *payrollengine.FormulaRates, relief bool) {
		in := FormulaInput{Type: ftype, Category: cat, Title: ftype + " " + cat, EffectiveFrom: from, IsCurrent: true}
		if relief {
			in.PersonalRelief = r.PersonalRelief
		}
		for _, b := range r.Bands {
			to := b.To
			if to.Equal(payrollengine.Inf) {
				to = decimal.Zero
			}
			in.Items = append(in.Items, FormulaItemInput{AmountFrom: b.From, AmountTo: to, DeductAmount: b.Amount, DeductPercentage: b.Rate.Mul(hundred)})
		}
		emp, empr := r.EmployeePercentage.Mul(hundred), r.EmployerPercentage.Mul(hundred)
		if emp.IsZero() {
			emp = hundred
		}
		in.EmployeePercentage, in.EmployerPercentage = &emp, &empr
		if _, err := svc.UpsertFormula(ctx, svc.SystemTenant(), in); err != nil {
			t.Fatalf("seed %s/%s: %v", ftype, cat, err)
		}
	}
	add("income", "primary", def.Income, true)
	add("income", "secondary", def.IncomeSecondary, false)
	add("deduction", "social_security_fund", def.NSSF, false)
	add("deduction", "shif", def.SHIF, false)
	add("deduction", "housing_levy", def.HousingLevy, false)
	for _, r := range []struct {
		title, limit, pct string
		actual            bool
	}{{"Personal Relief", "2400", "0", false}, {"Insurance Relief", "5000", "15", true}, {"Pension Relief", "30000", "100", true}} {
		svc.orm.PayrollRelief.Create().SetTenantID(svc.SystemTenant()).SetType("Deductible").SetTitle(r.title).
			SetActualAmount(r.actual).SetFixedLimit(decimal.RequireFromString(r.limit)).
			SetPercentage(decimal.RequireFromString(r.pct)).SetIsActive(true).SaveX(ctx)
	}
	if _, err := EnsurePlatformCatalogue(ctx, svc.orm, svc.SystemTenant()); err != nil {
		t.Fatal(err)
	}
}

func netPay(t *testing.T, ctx context.Context, svc *Service, tenant uuid.UUID, in payrollengine.EmployeeInput) payrollengine.PayslipResult {
	t.Helper()
	cfg, err := svc.BuildEngineConfig(ctx, tenant, *day(2026, 3, 1), true)
	if err != nil {
		t.Fatalf("config: %v", err)
	}
	res, err := payrollengine.Compute(cfg, in)
	if err != nil {
		t.Fatalf("compute: %v", err)
	}
	return res
}

// End to end: a tenant with nothing of its own lists and runs on the platform formulas; a
// platform edit reaches it; customising isolates it; reverting brings the platform back.
func TestIntegration_InheritCustomiseRevert(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	svc := NewService(client, sysT)
	seedPlatform(t, ctx, svc)
	gross := payrollengine.EmployeeInput{GrossPay: decimal.NewFromInt(100000), TaxCategory: "primary"}

	list, err := svc.ListFormulas(ctx, tenantA)
	if err != nil || len(list) != 5 {
		t.Fatalf("tenant must see the 5 platform formulas, got %d (%v)", len(list), err)
	}
	if got := netPay(t, ctx, svc, tenantA, gross).NetPay.StringFixed(2); got != "71617.65" {
		t.Fatalf("golden master through inherited platform formulas: %s", got)
	}

	// Customise SHIF for tenant A only: one formula copied, nothing else.
	var shifID uuid.UUID
	for _, f := range list {
		if f.Formula.Category == "shif" {
			shifID = f.Formula.ID
		}
	}
	own, err := svc.CustomiseFormula(ctx, tenantA, shifID)
	if err != nil {
		t.Fatal(err)
	}
	if n := client.PayrollFormula.Query().CountX(ctx); n != 6 {
		t.Errorf("customise must copy exactly one formula, have %d rows", n)
	}
	if _, err := svc.CustomiseFormula(ctx, tenantA, shifID); err == nil {
		t.Error("customising twice must be refused")
	}
	seven := decimal.NewFromInt(3)
	if _, err := svc.UpsertFormula(ctx, tenantA, FormulaInput{ID: &own.ID, Type: "deduction", Category: "shif", Title: "SHIF 3%",
		EffectiveFrom: day(2024, 1, 1), IsCurrent: true, Items: []FormulaItemInput{{DeductPercentage: seven}}}); err != nil {
		t.Fatal(err)
	}
	if got := netPay(t, ctx, svc, tenantA, gross).SHIFOrNHIF.StringFixed(2); got != "3000.00" {
		t.Errorf("tenant A SHIF after customising = %s, want 3000.00", got)
	}
	tenantB := uuid.New()
	if got := netPay(t, ctx, svc, tenantB, gross).NetPay.StringFixed(2); got != "71617.65" {
		t.Errorf("tenant B must be unaffected by tenant A's customisation: %s", got)
	}

	// A tenant cannot edit the platform row; the platform owner can, and it reaches tenant B.
	if _, err := svc.UpsertFormula(ctx, tenantB, FormulaInput{ID: &shifID, Type: "deduction", Category: "shif", Title: "x", IsCurrent: true}); err != ErrPlatformReadOnly {
		t.Errorf("tenant editing a platform formula: want ErrPlatformReadOnly, got %v", err)
	}
	if _, err := svc.UpsertFormula(ctx, sysT, FormulaInput{Type: "deduction", Category: "shif", Title: "SHIF 2026",
		EffectiveFrom: day(2026, 1, 1), IsCurrent: true, Items: []FormulaItemInput{{DeductPercentage: decimal.RequireFromString("2.5")}}}); err != nil {
		t.Fatal(err)
	}
	if got := netPay(t, ctx, svc, tenantB, gross).SHIFOrNHIF.StringFixed(2); got != "2500.00" {
		t.Errorf("platform edit must reach tenant B: SHIF %s", got)
	}
	// The earlier platform version still covers 2025 (closed the day before the new one).
	cfg2025, err := svc.BuildEngineConfig(ctx, tenantB, *day(2025, 6, 1), true)
	if err != nil {
		t.Fatal(err)
	}
	if !cfg2025.SHIF.Bands[0].Rate.Equal(decimal.RequireFromString("0.0275")) {
		t.Errorf("June 2025 must keep the 2.75%% version, got %s", cfg2025.SHIF.Bands[0].Rate)
	}
	if got := netPay(t, ctx, svc, tenantA, gross).SHIFOrNHIF.StringFixed(2); got != "3000.00" {
		t.Errorf("customised tenant A keeps its own SHIF after the platform edit: %s", got)
	}

	// Revert: tenant A inherits the platform again.
	if n, err := svc.RevertFormula(ctx, tenantA, own.ID); err != nil || n != 1 {
		t.Fatalf("revert removed %d (%v)", n, err)
	}
	if got := netPay(t, ctx, svc, tenantA, gross).SHIFOrNHIF.StringFixed(2); got != "2500.00" {
		t.Errorf("reverted tenant A must follow the platform: SHIF %s", got)
	}
}

// Reliefs and components resolve through per-tenant choices, never copied rows.
func TestIntegration_ReliefsAndComponents(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	svc := NewService(client, sysT)
	seedPlatform(t, ctx, svc)

	personal, err := svc.Relief(ctx, tenantA, "personal_relief")
	if err != nil || personal == nil || !personal.IsActive || personal.Source != SourcePlatform {
		t.Fatalf("personal relief must be inherited and active: %+v %v", personal, err)
	}
	ins := payrollengine.EmployeeInput{GrossPay: decimal.NewFromInt(100000), TaxCategory: "primary", InsurancePremium: decimal.NewFromInt(2000)}
	if got := netPay(t, ctx, svc, tenantA, ins).InsuranceRelief.StringFixed(2); got != "300.00" {
		t.Errorf("inherited insurance relief must apply in runs: %s", got)
	}
	if _, err := svc.SetReliefActive(ctx, tenantA, "insurance_relief", false); err != nil {
		t.Fatal(err)
	}
	if got := netPay(t, ctx, svc, tenantA, ins).InsuranceRelief; !got.IsZero() {
		t.Errorf("switched-off insurance relief still applied: %s", got)
	}
	if got := netPay(t, ctx, svc, uuid.New(), ins).InsuranceRelief.StringFixed(2); got != "300.00" {
		t.Errorf("other tenants keep insurance relief: %s", got)
	}
	if _, err := svc.RevertRelief(ctx, tenantA, "insurance_relief"); err != nil {
		t.Fatal(err)
	}
	if got := netPay(t, ctx, svc, tenantA, ins).InsuranceRelief.StringFixed(2); got != "300.00" {
		t.Errorf("reverted relief must apply again: %s", got)
	}

	// Components: full catalogue visible, statutory on, opt-in off, choices per tenant.
	deds, err := svc.ResolveComponents(ctx, tenantA, CategoryDeductions)
	if err != nil {
		t.Fatal(err)
	}
	byC := byCode(deds)
	if !byC["paye"].Active || byC["sacco"].Active {
		t.Fatalf("defaults: paye %v sacco %v", byC["paye"].Active, byC["sacco"].Active)
	}
	sacco := byC["sacco"].Component.ID
	if r, err := svc.SetComponentActive(ctx, tenantA, sacco, true); err != nil || !r.Active {
		t.Fatalf("opt in to SACCO: %+v %v", r, err)
	}
	amt := decimal.NewFromInt(1500)
	if r, err := svc.CustomiseComponent(ctx, tenantA, sacco, ComponentChoice{Amount: &amt}); err != nil || !r.Customised || !r.Amount.Equal(amt) || !r.Active {
		t.Fatalf("customise SACCO: %+v %v", r, err)
	}
	if n := client.PayrollComponent.Query().CountX(ctx); n != len(PlatformCatalogue()) {
		t.Errorf("choices must not copy components: %d rows", n)
	}
	// Statutory switch writes the tenant toggle and the engine skips the item.
	if _, err := svc.SetComponentActive(ctx, tenantA, byC["nita"].Component.ID, false); err != nil {
		t.Fatal(err)
	}
	cfg, err := svc.BuildEngineConfig(ctx, tenantA, *day(2026, 3, 1), true)
	if err != nil {
		t.Fatal(err)
	}
	if !cfg.Disabled[payrollengine.CompNITA] {
		t.Error("NITA switched off must be disabled in the engine config")
	}
	byID, err := svc.ComponentsByID(ctx, uuid.New(), []uuid.UUID{sacco})
	if err != nil || byID[sacco].Active || byID[sacco].Customised {
		t.Errorf("another tenant sees SACCO off and uncustomised: %+v", byID[sacco])
	}
	if r, err := svc.RevertComponent(ctx, tenantA, sacco); err != nil || r.Active || r.Customised {
		t.Errorf("revert SACCO: %+v %v", r, err)
	}

	// Relief copies identical to the platform are removed; a real customisation stays.
	svc.orm.PayrollRelief.Create().SetTenantID(tenantA).SetType("Deductible").SetTitle("Pension Relief").SetActualAmount(true).
		SetFixedLimit(decimal.NewFromInt(30000)).SetPercentage(decimal.NewFromInt(100)).SetIsActive(true).SaveX(ctx)
	svc.orm.PayrollRelief.Create().SetTenantID(tenantA).SetType("Deductible").SetTitle("Insurance Relief").SetActualAmount(true).
		SetFixedLimit(decimal.NewFromInt(6000)).SetPercentage(decimal.NewFromInt(15)).SetIsActive(true).SaveX(ctx)
	if n, err := svc.DedupeTenantReliefs(ctx, tenantA); err != nil || n != 1 {
		t.Errorf("dedupe removed %d (%v), want 1", n, err)
	}
}
