package employees

import (
	"context"
	"database/sql"
	"os"
	"strings"
	"testing"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// TestLookupOnPostgres: only the tenant's active employees, matched by name, staff number or email,
// by name. Needs ERP_TEST_DATABASE_URL (a throwaway schema is created and dropped).
func TestLookupOnPostgres(t *testing.T) {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_emp_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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
	client := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, db)))
	t.Cleanup(func() { _ = client.Close() })
	ctx := context.Background()
	if err := client.Schema.Create(ctx); err != nil {
		t.Fatal(err)
	}

	tenant, other := uuid.New(), uuid.New()
	add := func(tid uuid.UUID, first, last, number string, terminated, deleted bool) {
		t.Helper()
		if _, err := client.Employee.Create().SetTenantID(tid).SetFirstName(first).SetLastName(last).
			SetEmployeeNumber(number).SetNationalID(uuid.NewString()[:12]).SetEmail(strings.ToLower(first) + "@estate.test").
			SetTerminated(terminated).SetDeleted(deleted).Save(ctx); err != nil {
			t.Fatal(err)
		}
	}
	add(tenant, "Wanjiru", "Kamau", "MV/2026/001", false, false)
	add(tenant, "Otieno", "Odhiambo", "MV/2026/002", false, false)
	add(tenant, "Left", "Already", "MV/2026/003", true, false)
	add(tenant, "Removed", "Record", "MV/2026/004", false, true)
	add(other, "Wanjiru", "Elsewhere", "X/001", false, false)

	svc := NewService(client)
	all, err := svc.Lookup(ctx, tenant, "", 0)
	if err != nil {
		t.Fatal(err)
	}
	if len(all) != 2 || all[0].Name != "Otieno Odhiambo" || all[1].Name != "Wanjiru Kamau" {
		t.Fatalf("active staff by name: %+v", all)
	}
	for _, q := range []string{"wanj", "MV/2026/001", "wanjiru@"} {
		got, err := svc.Lookup(ctx, tenant, q, 10)
		if err != nil || len(got) != 1 || got[0].EmployeeNumber != "MV/2026/001" {
			t.Fatalf("search %q: %+v %v", q, got, err)
		}
	}
}
