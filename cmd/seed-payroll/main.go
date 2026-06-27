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

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/modules/defaults"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
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
	log.Printf("seed-payroll: global statutory rates ready under system tenant %s", systemTenant)
}

func seed(ctx context.Context, client *ent.Client, tenantID uuid.UUID) error {
	def := payrollengine.KRADefaults()
	// Effective dates use the public KRA commencement dates for each levy.
	formulas := []statutoryFormula{
		{"income", "primary", "P.A.Y.E. (Finance Act 2023)", "Finance Act 2023", def.Income, date(2023, 7, 1), true},
		{"income", "secondary", "P.A.Y.E. — Secondary Employment", "Finance Act 2023", def.IncomeSecondary, date(2023, 7, 1), false},
		{"deduction", "social_security_fund", "N.S.S.F.", "NSSF Act 2013", def.NSSF, date(2024, 2, 1), false},
		{"deduction", "shif", "S.H.I.F.", "SHIF Act 2023", def.SHIF, date(2024, 10, 1), false},
		{"deduction", "housing_levy", "Affordable Housing Levy", "Affordable Housing Act 2024", def.HousingLevy, date(2024, 3, 1), false},
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
