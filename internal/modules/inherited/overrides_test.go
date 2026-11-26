package inherited

import (
	"context"
	"database/sql"
	"os"
	"slices"
	"strings"
	"testing"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

func TestNameKeyAndTenants(t *testing.T) {
	for _, pair := range [][2]string{{"Annual Leave", " annual leave "}, {"GRADE A", "grade a"}} {
		if NameKey(pair[0]) != NameKey(pair[1]) {
			t.Fatalf("%q and %q must match", pair[0], pair[1])
		}
	}
	if NameKey("Annual Leave") == NameKey("Annual  Leave days") {
		t.Fatal("different names must not match")
	}
	system, tenant := uuid.New(), uuid.New()
	if got := Tenants(system, tenant); !slices.Equal(got, []uuid.UUID{tenant, system}) {
		t.Fatalf("company: %v", got)
	}
	if got := Tenants(system, system); !slices.Equal(got, []uuid.UUID{system}) {
		t.Fatalf("platform itself: %v", got)
	}
	if got := Tenants(uuid.Nil, tenant); !slices.Equal(got, []uuid.UUID{tenant}) {
		t.Fatalf("no platform: %v", got)
	}
}

type change struct {
	Description *string `json:"description,omitempty"`
}

// TestLoadSaveOverrides: records are per company and per kind, a save replaces the kind's set,
// and a company with none reads an empty set.
func TestLoadSaveOverrides(t *testing.T) {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_inh_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	if _, err := admin.Exec("CREATE SCHEMA " + schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() { _, _ = admin.Exec("DROP SCHEMA " + schema + " CASCADE"); _ = admin.Close() })
	sep := "?"
	if strings.Contains(url, "?") {
		sep = "&"
	}
	db, err := sql.Open("pgx", url+sep+"search_path="+schema)
	if err != nil {
		t.Fatal(err)
	}
	c := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, db)))
	t.Cleanup(func() { _ = c.Close() })
	ctx := context.Background()
	if err := c.Schema.Create(ctx); err != nil {
		t.Fatal(err)
	}

	a, b := uuid.New(), uuid.New()
	if m, err := Load[change](ctx, c, a, "k1"); err != nil || len(m) != 0 {
		t.Fatalf("empty: %v %v", m, err)
	}
	d := "changed"
	if err := Save(ctx, c, a, "k1", map[string]change{"x": {Description: &d}}); err != nil {
		t.Fatal(err)
	}
	if err := Save(ctx, c, a, "k2", map[string]change{"y": {}}); err != nil {
		t.Fatal(err)
	}
	m, err := Load[change](ctx, c, a, "k1")
	if err != nil || len(m) != 1 || *m["x"].Description != "changed" {
		t.Fatalf("company a, k1: %v %v", m, err)
	}
	if m, _ := Load[change](ctx, c, b, "k1"); len(m) != 0 {
		t.Fatalf("company b sees a's records: %v", m)
	}
	delete(m, "x")
	if err := Save(ctx, c, a, "k1", m); err != nil {
		t.Fatal(err)
	}
	if m, _ := Load[change](ctx, c, a, "k1"); len(m) != 0 {
		t.Fatalf("after revert: %v", m)
	}
	if m, _ := Load[change](ctx, c, a, "k2"); len(m) != 1 {
		t.Fatalf("another kind changed: %v", m)
	}
}
