// Command seed-payroll seeds the GLOBAL Kenyan statutory rate set (PAYE, NSSF, SHIF, Housing
// Levy) under the synthetic system tenant. Per feedback_shared_core_reference_data, statutory
// rates are shared reference data — NOT duplicated per tenant. Any tenant without its own
// current formula inherits these via payrollsettings.Service's system-tenant fallback
// (PAYROLL_SYSTEM_TENANT_ID, default 00000000-0000-0000-0000-0000000005ff).
//
// The rate values come from payrollengine.KRADefaults() — the SAME source the engine
// golden-master test uses — so the seeded national defaults can never diverge from the
// verified engine (Gross 100k -> Net 71,617.65).
//
// Idempotent: re-running skips any (type, category) that already has a formula under the
// system tenant. Safe to run on every deploy.
//
// Usage:
//
//	POSTGRES_MIGRATE_URL=postgres://... go run ./cmd/seed-payroll
package main

import (
	"context"
	"database/sql"
	"log"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/joho/godotenv"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformulaitem"
	"github.com/Bengo-Hub/erp-api/internal/modules/defaults"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

var hundred = decimal.NewFromInt(100)

// pct converts an engine rate fraction (0.06) to the stored percentage (6.00).
func pct(frac decimal.Decimal) decimal.Decimal { return frac.Mul(hundred) }

// boundTo maps an engine band upper bound to the stored amount_to: an infinite bound is stored
// as 0 (config_builder treats amount_to==0 as +Inf).
func boundTo(to decimal.Decimal) decimal.Decimal {
	if to.Equal(payrollengine.Inf) {
		return decimal.Zero
	}
	return to
}

// statutoryFormula describes one global formula to seed from a KRADefaults FormulaRates.
type statutoryFormula struct {
	ftype, category, title, regSource string
	rates                             *payrollengine.FormulaRates
	effectiveFrom                     time.Time
	withRelief                        bool
}

func main() {
	_ = godotenv.Load()
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("load config: %v", err)
	}
	dsn := cfg.Postgres.MigrateDSN()
	if dsn == "" {
		dsn = "postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable"
	}
	sqlDB, err := sql.Open("pgx", dsn)
	if err != nil {
		log.Fatalf("open db: %v", err)
	}
	defer func() { _ = sqlDB.Close() }()
	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, sqlDB)))
	defer func() { _ = client.Close() }()

	systemTenant, err := uuid.Parse(cfg.Payroll.SystemTenantID)
	if err != nil {
		log.Fatalf("invalid PAYROLL_SYSTEM_TENANT_ID %q: %v", cfg.Payroll.SystemTenantID, err)
	}

	ctx := context.Background()
	if err := seed(ctx, client, systemTenant); err != nil {
		log.Fatalf("seed-payroll: %v", err)
	}
	syncTreasuryRates(ctx, cfg, client, systemTenant)
	log.Printf("seed-payroll: global statutory rates ready under system tenant %s", systemTenant)
}

func seed(ctx context.Context, client *ent.Client, tenantID uuid.UUID) error {
	def := payrollengine.KRADefaults()
	// Effective dates use the public KRA commencement dates for each levy. NSSF is handled
	// separately (ensureNSSFYear4): its phased Third-Schedule limits need an upgrade path.
	formulas := []statutoryFormula{
		{"income", "primary", "P.A.Y.E. (Finance Act 2023)", "Finance Act 2023", def.Income, date(2023, 7, 1), true},
		{"income", "secondary", "P.A.Y.E. — Secondary Employment", "Finance Act 2023", def.IncomeSecondary, date(2023, 7, 1), false},
		{"deduction", "shif", "S.H.I.F.", "SHIF Act 2023", def.SHIF, date(2024, 10, 1), false},
		{"deduction", "housing_levy", "Affordable Housing Levy", "Affordable Housing Act 2024", def.HousingLevy, date(2024, 3, 1), false},
		{"deduction", "nita", "NITA Industrial Training Levy", "Industrial Training (Training Levy) Order, 2007", def.NITA, date(2007, 6, 1), false},
	}

	if err := ensureNSSFYear4(ctx, client, tenantID); err != nil {
		return err
	}

	for _, f := range formulas {
		exists, err := client.PayrollFormula.Query().
			Where(payrollformula.TenantID(tenantID), payrollformula.TypeEQ(f.ftype), payrollformula.CategoryEQ(f.category)).
			Exist(ctx)
		if err != nil {
			return err
		}
		if exists {
			log.Printf("  skip %s/%s (already seeded)", f.ftype, f.category)
			continue
		}
		if err := seedFormula(ctx, client, tenantID, f); err != nil {
			return err
		}
		log.Printf("  seeded %s/%s (%d bands)", f.ftype, f.category, len(f.rates.Bands))
	}
	// PAYE band 4 ends at 800,000 from the December 2026 payroll; earlier months keep 799,999.
	if applied, err := payrollsettings.EnsurePAYEBand4(ctx, client, tenantID); err != nil {
		return err
	} else if applied {
		log.Printf("  PAYE band 4 limit corrected to 800,000 from %s", payrollsettings.PAYEBand4From.Format("2006-01-02"))
	}
	// SHIF's KES 300 monthly minimum lives in the formula metadata (a band cannot express it).
	if n, err := payrollsettings.EnsureSHIFMinimum(ctx, client, tenantID); err != nil {
		return err
	} else if n > 0 {
		log.Printf("  set the SHIF minimum contribution on %d platform formula version(s)", n)
	}

	// Dated rules: per diem tax-free limit, quarterly fringe benefit tax, and the inactive 2026
	// bill PAYE bands. Only missing rows are added.
	if n, err := payrollsettings.EnsureDatedRules(ctx, client, tenantID); err != nil {
		return err
	} else if n > 0 {
		log.Printf("  added %d dated payroll rule(s)", n)
	}

	// Seed the default KRA reliefs (personal, insurance, AHL, disability, pension) under the
	// system tenant. Idempotent (skips by title). Per-tenant reuse via defaults.EnsureReliefs.
	if err := defaults.EnsureReliefsWithClient(ctx, client, tenantID); err != nil {
		return err
	}
	log.Printf("  seeded default KRA reliefs")

	// Global shared leave types under the system tenant; tenants inherit these unless they
	// define their own (leave.Service.ListCategories falls back to the system tenant).
	if err := defaults.NewService(client).EnsureLeaveCategories(ctx, tenantID); err != nil {
		return err
	}
	log.Printf("  seeded global leave types")

	// Global standard appraisal template + questions under the system tenant; tenants inherit
	// these unless they define their own (appraisals.Service.ListTemplates falls back).
	if err := defaults.NewService(client).EnsureAppraisalTemplate(ctx, tenantID); err != nil {
		return err
	}
	log.Printf("  seeded global appraisal template")

	// Platform catalogue of earnings, deductions and benefits. Tenants inherit it: statutory and
	// module-managed items are on, the rest are opt-in per tenant (payrollsettings.components).
	n, err := payrollsettings.EnsurePlatformCatalogue(ctx, client, tenantID)
	if err != nil {
		return err
	}
	log.Printf("  platform payroll component catalogue ready (%d added)", n)
	return nil
}

// syncTreasuryRates applies treasury's approved, newer statutory rate changes to the platform
// formulas. Best effort: an unconfigured or unreachable treasury leaves the seeded rates alone.
func syncTreasuryRates(ctx context.Context, cfg *config.Config, client *ent.Client, systemTenant uuid.UUID) {
	tc := treasury.NewClient(cfg.Services.TreasuryURL, cfg.Auth.APIKey, zap.NewNop())
	if !tc.Enabled() {
		log.Printf("  treasury rate sync skipped (treasury not configured)")
		return
	}
	rates, err := tc.ListStatutoryRates(ctx, systemTenant)
	if err != nil {
		log.Printf("  treasury rate sync skipped: %v", err)
		return
	}
	res, err := payrollsettings.NewService(client, systemTenant).SyncTreasuryRates(ctx, rates)
	if err != nil {
		log.Printf("  treasury rate sync failed: %v", err)
	}
	for _, r := range res {
		log.Printf("  treasury rates %s/%s: %s (effective %s)", r.Type, r.Category, r.Action, r.EffectiveFrom.Format("2006-01-02"))
	}
}

// nssfYear4UEL is the Year-4 Tier II upper earnings limit — the marker distinguishing an
// up-to-date NSSF formula from an earlier phase.
var nssfYear4UEL = decimal.NewFromInt(108000)

// ensureNSSFYear4 brings the system tenant's NSSF formula to the Act 2013 Third Schedule
// YEAR 4 limits (effective 1 Feb 2026: tiers 9,000 / 108,000, max 6,480/side). An existing
// current formula on earlier limits is retired (is_current=false, effective_to 2026-01-31)
// and the Year-4 row seeded as current — the partial unique index allows only one current
// row per (tenant, type, category). Idempotent: a current row already at the Year-4 UEL is
// left untouched.
func ensureNSSFYear4(ctx context.Context, client *ent.Client, tenantID uuid.UUID) error {
	current, err := client.PayrollFormula.Query().
		Where(
			payrollformula.TenantID(tenantID),
			payrollformula.TypeEQ("deduction"),
			payrollformula.CategoryEQ("social_security_fund"),
			payrollformula.IsCurrent(true),
		).
		First(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return err
	}
	if current != nil {
		items, err := client.PayrollFormulaItem.Query().
			Where(payrollformulaitem.TenantID(tenantID), payrollformulaitem.FormulaID(current.ID)).
			All(ctx)
		if err != nil {
			return err
		}
		for _, it := range items {
			if it.AmountTo.GreaterThanOrEqual(nssfYear4UEL) {
				log.Printf("  skip deduction/social_security_fund (already on Year 4 limits)")
				return nil
			}
		}
		// Retire the earlier-phase row; Year 4 commences 2026-02-01.
		if _, err := current.Update().
			SetIsCurrent(false).
			SetEffectiveTo(date(2026, 1, 31)).
			Save(ctx); err != nil {
			return err
		}
		log.Printf("  retired earlier NSSF limits (effective_to 2026-01-31)")
	}
	if err := seedFormula(ctx, client, tenantID, statutoryFormula{
		ftype:         "deduction",
		category:      "social_security_fund",
		title:         "N.S.S.F. (Year 4)",
		regSource:     "NSSF Act 2013 — Third Schedule, Year 4",
		rates:         payrollengine.NSSFYear4(),
		effectiveFrom: date(2026, 2, 1),
	}); err != nil {
		return err
	}
	log.Printf("  seeded deduction/social_security_fund Year 4 (tiers 9,000/108,000)")
	return nil
}

func seedFormula(ctx context.Context, client *ent.Client, tenantID uuid.UUID, f statutoryFormula) error {
	create := client.PayrollFormula.Create().
		SetTenantID(tenantID).
		SetType(f.ftype).
		SetCategory(f.category).
		SetTitle(f.title).
		SetUnit("KES").
		SetProgressive(f.ftype == "income").
		SetIsCurrent(true).
		SetEffectiveFrom(f.effectiveFrom).
		SetRegulatorySource(f.regSource).
		SetVersion("1.0")
	if f.withRelief {
		create = create.SetPersonalRelief(f.rates.PersonalRelief)
	}
	if f.rates.MinimumContribution.IsPositive() {
		create = create.SetMetadata(map[string]any{"minimum_contribution": f.rates.MinimumContribution.StringFixed(2)})
	}
	formula, err := create.Save(ctx)
	if err != nil {
		return err
	}

	// Bands -> formula items.
	for _, b := range f.rates.Bands {
		amount := b.Amount
		if amount.IsZero() {
			amount = decimal.Zero
		}
		if _, err := client.PayrollFormulaItem.Create().
			SetTenantID(tenantID).
			SetFormulaID(formula.ID).
			SetAmountFrom(b.From).
			SetAmountTo(boundTo(b.To)).
			SetDeductAmount(amount).
			SetDeductPercentage(pct(b.Rate)).
			Save(ctx); err != nil {
			return err
		}
	}

	// Employee/employer split (NSSF + Housing are matched; SHIF/PAYE are employee-only).
	empPct := f.rates.EmployeePercentage
	if empPct.IsZero() {
		empPct = decimal.NewFromInt(1)
	}
	if _, err := client.PayrollSplitRatio.Create().
		SetTenantID(tenantID).
		SetFormulaID(formula.ID).
		SetEmployeePercentage(pct(empPct)).
		SetEmployerPercentage(pct(f.rates.EmployerPercentage)).
		Save(ctx); err != nil {
		return err
	}
	return nil
}

func date(y int, m time.Month, d int) time.Time {
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}
