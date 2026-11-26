package holidays

import (
	"context"
	"database/sql"
	"os"
	"slices"
	"strings"
	"testing"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/publicholiday"
)

func testClient(t *testing.T) *ent.Client {
	t.Helper()
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_hol_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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
	if err := c.Schema.Create(context.Background()); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return c
}

// TestSundayRule: a Part I day on a Sunday moves to the first following day that is not itself a
// holiday, and the Sunday stops being one.
func TestSundayRule(t *testing.T) {
	got, err := observed([]dated{
		{"2027-10-10", "Mazingira Day"}, // Sunday
		{"2027-12-25", "Christmas Day"}, // Saturday
		{"2027-12-26", "Boxing Day"},    // Sunday
		{"2028-01-02", "A"},             // Sunday, Monday taken below
		{"2028-01-03", "B"},
	})
	if err != nil {
		t.Fatal(err)
	}
	want := []dated{
		{"2027-10-11", "Mazingira Day (observed)"},
		{"2027-12-25", "Christmas Day"},
		{"2027-12-27", "Boxing Day (observed)"},
		{"2028-01-04", "A (observed)"},
		{"2028-01-03", "B"},
	}
	if !slices.Equal(got, want) {
		t.Fatalf("got %v", got)
	}
	// The shipped list: no Sunday is left, and no two holidays share a date.
	days, err := observed(kenya)
	if err != nil {
		t.Fatal(err)
	}
	seen := map[string]bool{}
	for _, d := range days {
		day, _ := time.Parse("2006-01-02", d.date)
		if day.Weekday() == time.Sunday || seen[d.date] {
			t.Fatalf("%v", d)
		}
		seen[d.date] = true
	}
}

// TestPlatformHolidaysInherited: the platform's holidays are seeded once ever, every tenant sees
// them without a copy, a tenant can switch one off and on again, and attendance only counts the
// active ones.
func TestPlatformHolidaysInherited(t *testing.T) {
	c := testClient(t)
	ctx := context.Background()
	system, tenant := uuid.New(), uuid.New()

	n, err := EnsurePlatform(ctx, c, system)
	if err != nil || n != len(kenya) {
		t.Fatalf("seed: %d %v", n, err)
	}
	// The platform owner deletes one; it does not come back.
	c.PublicHoliday.Delete().Where(publicholiday.TenantID(system), publicholiday.Name("Boxing Day (observed)")).ExecX(ctx)
	if n, err := EnsurePlatform(ctx, c, system); err != nil || n != 0 {
		t.Fatalf("second seed: %d %v", n, err)
	}
	if got := c.PublicHoliday.Query().CountX(ctx); got != len(kenya)-1 {
		t.Fatalf("rows: %d", got)
	}

	own := c.PublicHoliday.Create().SetTenantID(tenant).SetName("Company day").SetDate(time.Date(2027, 3, 1, 0, 0, 0, 0, time.UTC)).SaveX(ctx)
	all, err := List(ctx, c, system, tenant, time.Time{}, time.Time{})
	if err != nil || len(all) != len(kenya) {
		t.Fatalf("list: %d %v", len(all), err)
	}
	if c.PublicHoliday.Query().Where(publicholiday.TenantID(tenant)).CountX(ctx) != 1 {
		t.Fatal("platform holidays were copied to the tenant")
	}

	labour := c.PublicHoliday.Query().Where(publicholiday.TenantID(system), publicholiday.Name("Labour Day")).OnlyX(ctx)
	if _, err := SetActive(ctx, c, system, tenant, labour.ID, false); err != nil {
		t.Fatal(err)
	}
	may := func() []string {
		rows, err := Active(ctx, c, system, tenant, time.Date(2027, 3, 1, 0, 0, 0, 0, time.UTC), time.Date(2027, 6, 1, 0, 0, 0, 0, time.UTC))
		if err != nil {
			t.Fatal(err)
		}
		out := []string{}
		for _, r := range rows {
			out = append(out, r.Name)
		}
		slices.Sort(out)
		return out
	}
	if got := may(); !slices.Equal(got, []string{"Company day", "Easter Monday", "Good Friday"}) {
		t.Fatalf("switched off: %v", got)
	}
	// Another tenant still has it.
	other, err := Active(ctx, c, system, uuid.New(), time.Date(2027, 5, 1, 0, 0, 0, 0, time.UTC), time.Date(2027, 5, 2, 0, 0, 0, 0, time.UTC))
	if err != nil || len(other) != 1 {
		t.Fatalf("other tenant: %v %v", other, err)
	}
	if _, err := SetActive(ctx, c, system, tenant, labour.ID, true); err != nil {
		t.Fatal(err)
	}
	if got := may(); !slices.Equal(got, []string{"Company day", "Easter Monday", "Good Friday", "Labour Day"}) {
		t.Fatalf("switched on again: %v", got)
	}
	// The tenant's own holiday is not switched; it is edited or deleted.
	if _, err := SetActive(ctx, c, system, tenant, own.ID, false); err != ErrNotInherited {
		t.Fatalf("own holiday: %v", err)
	}
}
