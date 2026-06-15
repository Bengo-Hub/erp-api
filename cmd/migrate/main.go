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
	drv := entsql.OpenDB(dialect.Postgres, sqlDB)
	client := ent.NewClient(ent.Driver(drv))
	defer func() { _ = client.Close() }()

	if err := client.Schema.Create(ctx, schema.WithDir(migrate.Dir)); err != nil {
		log.Fatalf("apply migrations: %v", err)
	}

	fmt.Println("erp-api migrations applied successfully")
}
