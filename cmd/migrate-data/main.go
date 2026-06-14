// Command migrate-data is the one-shot ETL that moves the legacy Django ERP data
// (bengo_erp, 158-table Django schema) into the new Go/Ent schema living in the SAME
// database (plan §0c). It reads each legacy table, transforms Django types to Ent
// (decimal money, datetimes -> Africa/Nairobi, int PKs -> deterministic UUIDv5,
// tenant_id backfill via Employee.organisation -> business_details.tenant_id), and
// writes Ent rows in FK-dependency order (docs/data-migration.md §3).
//
// SCOPE: the KEPT HR/Ops domains only (employees, payroll, leave, attendance,
// recruitment, training, appraisals, performance, tasks, approvals, business config).
// Decomposed domains (finance/inventory/ordering/projects/...) are NOT migrated — they
// belong to their owner services.
//
// SAFETY: idempotent (upsert-by-natural-key / deterministic-UUID skip-if-exists, safe to
// re-run during rehearsal + final delta); degrades cleanly when a legacy source table is
// absent (skip + warn) so --dry-run runs on a local DB without the Django schema.
//
// Usage:
//
//	POSTGRES_URL=postgres://... go run ./cmd/migrate-data --dry-run
//	POSTGRES_URL=postgres://... go run ./cmd/migrate-data --only=employee --verbose
//	POSTGRES_URL=postgres://... go run ./cmd/migrate-data            # real run (writes)
//
// NEVER hardcodes credentials — POSTGRES_URL comes from env / the k8s secret (see
// docs/data-migration-runbook.md for the prod port-forward recipe).
package main

import (
	"context"
	"database/sql"
	"flag"
	"log"
	"os"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/joho/godotenv"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
)

func main() {
	_ = godotenv.Load()

	dryRun := flag.Bool("dry-run", false, "read + transform + report counts, perform NO writes")
	only := flag.String("only", "", "migrate only this legacy Django table (e.g. --only=employee)")
	verbose := flag.Bool("verbose", false, "log every row decision")
	defaultTenant := flag.String("default-tenant", "", "tenant_id UUID to assign to HR rows whose organisation resolves to no tenant (omit to hard-fail such rows)")
	flag.Parse()

	dsn := os.Getenv("POSTGRES_URL")
	if dsn == "" {
		dsn = os.Getenv("POSTGRES_MIGRATE_URL")
	}
	if dsn == "" {
		dsn = "postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable"
	}
	destSchema := os.Getenv("DB_SCHEMA")
	if destSchema == "" {
		destSchema = "erp"
	}

	// READ from the legacy Django tables in the public schema; WRITE the new Ent rows into the
	// erp schema (the two collide by name in the same bengo_erp DB — plan §0c / runbook). Two
	// connections with different search_path keeps reads/writes unambiguous without qualifying
	// every query.
	readDB, err := sql.Open("pgx", config.EnsureSearchPath(dsn, "public"))
	if err != nil {
		log.Fatalf("open read db (public): %v", err)
	}
	defer func() { _ = readDB.Close() }()
	if err := readDB.Ping(); err != nil {
		log.Fatalf("read db ping: %v", err)
	}

	writeDB, err := sql.Open("pgx", config.EnsureSearchPath(dsn, destSchema))
	if err != nil {
		log.Fatalf("open write db (%s): %v", destSchema, err)
	}
	defer func() { _ = writeDB.Close() }()
	if err := writeDB.Ping(); err != nil {
		log.Fatalf("write db ping: %v", err)
	}

	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, writeDB)))
	defer func() { _ = client.Close() }()

	m := &Migrator{
		db:      readDB,
		client:  client,
		ctx:     context.Background(),
		dryRun:  *dryRun,
		only:    *only,
		verbose: *verbose,
	}
	if *defaultTenant != "" {
		t, err := uuid.Parse(*defaultTenant)
		if err != nil {
			log.Fatalf("invalid --default-tenant: %v", err)
		}
		m.defaultTenant = &t
	}

	if m.dryRun {
		log.Println("=== DRY RUN: no writes will be performed ===")
	}
	if err := m.loadTenantMap(); err != nil {
		log.Fatalf("load tenant map: %v", err)
	}

	m.run()
	m.reconcile()
}

// run executes every in-scope table migration in FK-dependency order
// (docs/data-migration.md §3). Each step is wrapped in guard() so a missing source table or
// a per-table error never aborts the whole run — the reconcile report surfaces the outcome.
func (m *Migrator) run() {
	// 2-3. reference + business config (no HR FKs).
	m.migrateDepartments()
	m.migrateJobTitles()
	m.migrateCompanySettings()
	m.migrateDocumentSequences()
	m.migrateLeaveCategories()

	// 5. HR core (employees first — everything else FKs to it).
	m.migrateEmployees()
	m.migrateBankAccounts()
	m.migrateHRDetails()
	m.migrateSalaryDetails()
	m.migrateContracts()

	// 8-9. payroll txns + leave (depend on employees).
	m.migratePayslips()
	m.migrateLeaveRequests()
}
