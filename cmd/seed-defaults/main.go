// Command seed-defaults seeds the shared settings once on the platform tenant (national holidays,
// leave types, job groups A to G, the default appraisal template with its questions, and sample
// goals), which every company inherits without a copy, and each company's own document sequences
// for every known tenant shadow (auth_tenants).
//
// Idempotent: every Ensure* skips a kind that already has rows. Safe to run on every deploy.
//
// Usage:
//
//	POSTGRES_MIGRATE_URL=postgres://... go run ./cmd/seed-defaults
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

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/defaults"
	"github.com/Bengo-Hub/erp-api/internal/modules/holidays"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

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

	ctx := context.Background()
	svc := defaults.NewService(client)

	// Kenya's national holidays belong to the platform tenant; every company inherits them. Each
	// date is added once ever, so one the platform owner removed does not come back.
	if system, err := uuid.Parse(cfg.Payroll.SystemTenantID); err != nil {
		log.Printf("seed-defaults: national holidays skipped: invalid system tenant: %v", err)
	} else {
		hctx, cancel := context.WithTimeout(ctx, 2*time.Minute)
		n, err := holidays.EnsurePlatform(hctx, client, system)
		if err != nil {
			log.Printf("seed-defaults: national holidays: %v (added %d)", err, n)
		} else {
			log.Printf("seed-defaults: national holidays: added %d", n)
		}
		// Leave types, job groups, the appraisal template and sample goals: seeded once on the
		// platform tenant, inherited by every company, never copied into one.
		if err := svc.EnsurePlatform(hctx, system); err != nil {
			log.Printf("seed-defaults: platform settings: %v", err)
		}
		cancel()
	}

	tenants, err := client.AuthTenant.Query().All(ctx)
	if err != nil {
		log.Fatalf("list tenants: %v", err)
	}
	if len(tenants) == 0 {
		log.Println("seed-defaults: no tenant shadows yet — nothing to seed")
		return
	}
	// Payroll reliefs, formulas and components are platform rows every tenant inherits; reliefs
	// copied per tenant by an earlier bootstrap are removed when they repeat the platform relief
	// exactly, so platform rate changes reach those tenants too.
	systemTenant, _ := uuid.Parse(cfg.Payroll.SystemTenantID)
	payroll := payrollsettings.NewService(client, systemTenant)
	for _, t := range tenants {
		if err := svc.EnsureAll(ctx, t.ID); err != nil {
			log.Fatalf("seed-defaults: tenant %s (%s): %v", t.Slug, t.ID, err)
		}
		if n, err := payroll.DedupeTenantReliefs(ctx, t.ID); err != nil {
			log.Printf("seed-defaults: tenant %s: relief dedupe skipped: %v", t.Slug, err)
		} else if n > 0 {
			log.Printf("seed-defaults: tenant %s: removed %d relief copies identical to the platform reliefs", t.Slug, n)
		}
		log.Printf("seed-defaults: ensured defaults for tenant %s (%s)", t.Slug, t.ID)
	}
	log.Printf("seed-defaults: done (%d tenants)", len(tenants))
}
