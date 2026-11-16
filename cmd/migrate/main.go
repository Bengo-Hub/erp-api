// Command migrate applies the erp-api Atlas versioned migrations to Postgres.
// It is the production migration entrypoint (the HTTP server never auto-migrates in
// prod — see cmd/server). Mirrors inventory-service/cmd/migrate.
//
// Usage:
//
//	POSTGRES_MIGRATE_URL=postgres://... go run ./cmd/migrate
package main

import (
	"context"
	"database/sql"
	"fmt"
	"log"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"entgo.io/ent/dialect/sql/schema"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/joho/godotenv"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/migrate"
)

// migrationLockKey serialises concurrent migration runs (any constant unique to this service).
const migrationLockKey int64 = 0x6572705f6d696772 // "erp_migr"

func main() {
	_ = godotenv.Load()

	// migrate connects DIRECTLY to postgresql (bypasses pgbouncer) per platform convention.
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

	if err := sqlDB.Ping(); err != nil {
		log.Fatalf("db ping: %v", err)
	}

	ctx := context.Background()
	// One connection, so the advisory lock and every migration statement share one session; the
	// lock makes concurrent runs (two replicas' init containers) apply migrations one at a time.
	sqlDB.SetMaxOpenConns(1)
	sqlDB.SetMaxIdleConns(1)
	if _, err := sqlDB.ExecContext(ctx, "SELECT pg_advisory_lock($1)", migrationLockKey); err != nil {
		log.Fatalf("acquire migration lock: %v", err)
	}
	unlock := func() {
		if _, err := sqlDB.ExecContext(context.Background(), "SELECT pg_advisory_unlock($1)", migrationLockKey); err != nil {
			log.Printf("release migration lock: %v", err)
		}
	}

	drv := entsql.OpenDB(dialect.Postgres, sqlDB)
	client := ent.NewClient(ent.Driver(drv))
	defer func() { _ = client.Close() }()

	if err := dropRetiredIndexes(ctx, sqlDB); err != nil {
		unlock()
		log.Fatalf("drop retired indexes: %v", err)
	}
	if err := client.Schema.Create(ctx, schema.WithDir(migrate.Dir)); err != nil {
		unlock()
		log.Fatalf("apply migrations: %v", err)
	}
	unlock()

	fmt.Println("erp-api migrations applied successfully")
}

// retiredIndexes are unique indexes the schema no longer declares. The online diff never drops an
// index (WithDropIndex is off), so one that would now reject valid rows is dropped here first.
//
//   - timesheetentry_tenant_id_timesheet_id_date: one entry per date allowed a single project a
//     day. Entries are now unique per (date, project, task), the index Schema.Create adds below.
var retiredIndexes = []string{"timesheetentry_tenant_id_timesheet_id_date"}

func dropRetiredIndexes(ctx context.Context, db *sql.DB) error {
	for _, name := range retiredIndexes {
		if _, err := db.ExecContext(ctx, `DROP INDEX IF EXISTS "`+name+`"`); err != nil {
			return fmt.Errorf("%s: %w", name, err)
		}
	}
	return nil
}
