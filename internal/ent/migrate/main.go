//go:build ignore

// Atlas versioned-migration generator (mirrors inventory-service workflow).
//
// Usage:
//
//	go run -mod=mod ./internal/ent/migrate <migration_name>
//
// It replays existing migrations against a clean dev schema (search_path=ent_dev) to
// compute the diff for the new named migration. Requires a reachable Postgres
// (POSTGRES_MIGRATE_URL / POSTGRES_URL, default local bengo_erp).
package main

import (
	"context"
	"log"
	"os"
	"strings"

	atlasmigrate "ariga.io/atlas/sql/migrate"
	"entgo.io/ent/dialect"
	"entgo.io/ent/dialect/sql/schema"
	_ "github.com/jackc/pgx/v5/stdlib"
	_ "github.com/lib/pq" // registers the "postgres" driver Atlas ModeReplay expects

	"github.com/Bengo-Hub/erp-api/internal/ent/migrate"
)

func main() {
	if len(os.Args) != 2 {
		log.Fatalln("migration name is required. use: 'go run -mod=mod ./internal/ent/migrate <name>'")
	}
	ctx := context.Background()

	dir, err := atlasmigrate.NewLocalDir("internal/ent/migrate/migrations")
	if err != nil {
		log.Fatalf("creating atlas migration directory: %v", err)
	}

	opts := []schema.MigrateOption{
		schema.WithDir(dir),
		schema.WithMigrationMode(schema.ModeReplay),
		schema.WithDialect(dialect.Postgres),
		schema.WithFormatter(atlasmigrate.DefaultFormatter),
	}

	dbURL := os.Getenv("POSTGRES_MIGRATE_URL")
	if dbURL == "" {
		dbURL = os.Getenv("POSTGRES_URL")
	}
	if dbURL == "" {
		dbURL = "postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable"
	}

	// Use a clean dev schema (ent_dev) so Atlas can compute the diff in isolation.
	devURL := dbURL
	if strings.Contains(devURL, "?") {
		devURL += "&search_path=ent_dev"
	} else {
		devURL += "?search_path=ent_dev"
	}

	if err := migrate.NamedDiff(ctx, devURL, os.Args[1], opts...); err != nil {
		log.Fatalf("generating migration: %v", err)
	}
	log.Printf("migration %q generated", os.Args[1])
}
