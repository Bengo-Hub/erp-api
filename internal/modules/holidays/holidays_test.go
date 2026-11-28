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
		{"2027-10-10", "Mazingira Day", "mazingira_day"}, // Sunday
		{"2027-12-25", "Christmas Day", "christmas"},     // Saturday
		{"2027-12-26", "Boxing Day", "boxing_day"},       // Sunday
		{"2028-01-02", "A", ""},                          // Sunday, Monday taken below
		{"2028-01-03", "B", ""},
	})
	if err != nil {
		t.Fatal(err)
	}
	want := []dated{
		{"2027-10-11", "Mazingira Day (observed)", "mazingira_day"},
		{"2027-12-25", "Christmas Day", "christmas"},
		{"2027-12-27", "Boxing Day (observed)", "boxing_day"},
		{"2028-01-04", "A (observed)", ""},
		{"2028-01-03", "B", ""},
	}
	if !slices.Equal(got, want) {
		t.Fatalf("got %v", got)
	}
	// The generated calendar, many years: no Sunday is left, and no two holidays share a date.
	days, err := observed(calendar(FirstYear, 2060))
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

// TestCalendarRules: the rules give the right days in known years. Easter Sunday was 5 April 2026
// and is 28 March 2027 and 16 April 2028; 2026 has all ten Part I days and no Sunday among them.
func TestCalendarRules(t *testing.T) {
	for year, want := range map[int]string{2026: "2026-04-05", 2027: "2027-03-28", 2028: "2028-04-16", 2038: "2038-04-25"} {
		if got := easterSunday(year).Format("2006-01-02"); got != want {
			t.Errorf("easter %d = %s, want %s", year, got, want)
		}
	}
	days, err := observed(calendar(2026, 2026))
	if err != nil {
		t.Fatal(err)
	}
	byKey := map[string]string{}
	for _, d := range days {
		byKey[d.key] = d.date
	}
	want := map[string]string{
		"new_year": "2026-01-01", "good_friday": "2026-04-03", "easter_monday": "2026-04-06",
		"labour_day": "2026-05-01", "madaraka_day": "2026-06-01", "mazingira_day": "2026-10-10",
		"mashujaa_day": "2026-10-20", "jamhuri_day": "2026-12-12", "christmas": "2026-12-25", "boxing_day": "2026-12-26",
	}
	if len(days) != len(want) {
		t.Fatalf("2026 has %d days: %v", len(days), days)
	}
	for k, v := range want {
		if byKey[k] != v {
			t.Errorf("%s = %s, want %s", k, byKey[k], v)
		}
	}
	for name, want := range map[string]string{"Boxing Day (observed)": "boxing_day", "labour day": "labour_day", "Company day": ""} {
		if got := KeyOf(name); got != want {
			t.Errorf("KeyOf(%q) = %q, want %q", name, got, want)
		}
	}
	// Mazingira Day is in the Schedule from 2024 only.
	for _, d := range calendar(2023, 2023) {
		if d.key == "mazingira_day" {
			t.Errorf("Mazingira Day in 2023: %v", d)
		}
	}
}

// TestPlatformHolidaysInherited: the platform's holidays are seeded once ever, every tenant sees
// them without a copy, a tenant can switch one off and on again, and attendance only counts the
// active ones.
func TestPlatformHolidaysInherited(t *testing.T) {
	c := testClient(t)
	ctx := context.Background()
	system, tenant := uuid.New(), uuid.New()
	now = func() time.Time { return time.Date(2026, 11, 28, 0, 0, 0, 0, time.UTC) }
	t.Cleanup(func() { now = time.Now })
	kenya := calendar(FirstYear, 2027) // what this horizon seeds: all of 2026 and 2027

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
	for _, h := range all {
		if (h.Key == "") != (h.ID == own.ID) {
			t.Errorf("%s key %q", h.Name, h.Key)
		}
	}
	if c.PublicHoliday.Query().Where(publicholiday.TenantID(tenant)).CountX(ctx) != 1 {
		t.Fatal("platform holidays were copied to the tenant")
	}

	labour := c.PublicHoliday.Query().Where(publicholiday.TenantID(system), publicholiday.Name("Labour Day"),
		publicholiday.Date(time.Date(2027, 5, 1, 0, 0, 0, 0, time.UTC))).OnlyX(ctx)
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
