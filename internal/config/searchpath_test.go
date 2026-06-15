package config

import (
	"net/url"
	"strings"
	"testing"
)

// DSN is the runtime connection (pgbouncer): returns POSTGRES_URL verbatim, no search_path.
func TestDSNIsPgbouncerURLNoSearchPath(t *testing.T) {
	c := PostgresConfig{URL: "postgres://u:p@pgbouncer.infra:5432/bengo_erp?sslmode=disable"}
	if got := c.DSN(); got != c.URL {
		t.Errorf("DSN()=%q, want %q (verbatim URL)", got, c.URL)
	}
	if strings.Contains(c.DSN(), "search_path") {
		t.Errorf("DSN must not set search_path (breaks pgbouncer pooling): %q", c.DSN())
	}
}

// MigrateDSN prefers POSTGRES_MIGRATE_URL, else builds a direct DSN from DB_* components.
func TestMigrateDSN(t *testing.T) {
	// explicit migrate URL wins
	c := PostgresConfig{URL: "x", MigrateURL: "postgres://direct/db"}
	if got := c.MigrateDSN(); got != "postgres://direct/db" {
		t.Errorf("MigrateDSN with MigrateURL=%q", got)
	}
	// built from components when Host set
	c = PostgresConfig{URL: "pgb", Host: "postgresql.infra", Port: "5432", User: "admin_user", Password: "pw", Name: "bengo_erp", SSLMode: "disable"}
	got := c.MigrateDSN()
	u, err := url.Parse(got)
	if err != nil {
		t.Fatalf("MigrateDSN unparseable: %q (%v)", got, err)
	}
	if u.Host != "postgresql.infra:5432" {
		t.Errorf("host=%q want postgresql.infra:5432", u.Host)
	}
	if u.Path != "/bengo_erp" {
		t.Errorf("path=%q want /bengo_erp", u.Path)
	}
	if u.Query().Get("sslmode") != "disable" {
		t.Errorf("sslmode=%q want disable", u.Query().Get("sslmode"))
	}
	// fallback to URL when no Host/MigrateURL
	c = PostgresConfig{URL: "pgb"}
	if got := c.MigrateDSN(); got != "pgb" {
		t.Errorf("MigrateDSN fallback=%q want pgb", got)
	}
}
