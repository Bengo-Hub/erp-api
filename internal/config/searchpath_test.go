package config

import (
	"net/url"
	"testing"
)

func TestEnsureSearchPath(t *testing.T) {
	cases := []struct{ dsn, schema, want string }{
		{"postgres://u:p@h:5432/bengo_erp?sslmode=disable", "erp", "erp"},
		{"postgres://u:p@h:5432/bengo_erp?sslmode=disable", "public", "public"},
		{"postgres://u:p@h:5432/bengo_erp", "erp", "erp"},
		{"postgres://u:p@h:5432/bengo_erp?search_path=public&sslmode=disable", "erp", "erp"}, // overrides existing
	}
	for _, c := range cases {
		got := EnsureSearchPath(c.dsn, c.schema)
		u, err := url.Parse(got)
		if err != nil {
			t.Fatalf("EnsureSearchPath(%q,%q) produced unparseable dsn %q: %v", c.dsn, c.schema, got, err)
		}
		if sp := u.Query().Get("search_path"); sp != c.want {
			t.Errorf("EnsureSearchPath(%q,%q) search_path=%q, want %q (full: %q)", c.dsn, c.schema, sp, c.want, got)
		}
	}
	// empty schema returns dsn unchanged
	if got := EnsureSearchPath("postgres://x/y", ""); got != "postgres://x/y" {
		t.Errorf("empty schema should pass through, got %q", got)
	}
}

func TestPostgresDSNUsesSchema(t *testing.T) {
	c := PostgresConfig{URL: "postgres://u:p@h:5432/bengo_erp?sslmode=disable", Schema: "erp"}
	u, _ := url.Parse(c.DSN())
	if sp := u.Query().Get("search_path"); sp != "erp" {
		t.Errorf("DSN search_path=%q, want erp", sp)
	}
}
