// Command seed-defaults seeds per-tenant HR/Ops reference data defaults — job groups (salary
// grades A–G), leave categories, a default appraisal template + questions, default document
// sequences, and the KRA reliefs — for every known tenant shadow (auth_tenants). These are
// tenant-scoped business config (NOT shared global reference data, per
// feedback_shared_core_reference_data), so they are seeded once per tenant.
//
// Idempotent: every Ensure* skips rows that already exist. Safe to run on every deploy. New
// tenants also get the document sequences + (the rest are also lazily bootstrapped) the first
// time they save company settings (business.UpsertSettings).
//
// Usage:
//
//	POSTGRES_MIGRATE_URL=postgres://... go run ./cmd/seed-defaults
package main

import (
	"context"
	"database/sql"
	"log"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/joho/godotenv"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/defaults"
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

	tenants, err := client.AuthTenant.Query().All(ctx)
	if err != nil {
		log.Fatalf("list tenants: %v", err)
	}
	if len(tenants) == 0 {
		log.Println("seed-defaults: no tenant shadows yet — nothing to seed")
		return
	}
	for _, t := range tenants {
		if err := svc.EnsureAll(ctx, t.ID); err != nil {
			log.Fatalf("seed-defaults: tenant %s (%s): %v", t.Slug, t.ID, err)
		}
		log.Printf("seed-defaults: ensured defaults for tenant %s (%s)", t.Slug, t.ID)
	}
	log.Printf("seed-defaults: done (%d tenants)", len(tenants))
}
