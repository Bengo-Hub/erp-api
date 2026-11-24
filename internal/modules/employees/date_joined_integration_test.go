package employees

import (
	"context"
	"database/sql"
	"os"
	"strings"
	"testing"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
)

// A zero date joined clears the stored date, nil leaves it, and on an employee without employment
// details (or one being created) it stores nothing.
func TestDateJoinedClears(t *testing.T) {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_dj_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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
		t.Fatalf("schema: %v", err)
	}

	tenant := uuid.New()
	svc := NewService(client)
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("A").SaveX(ctx)
	joined := time.Date(2026, 3, 1, 0, 0, 0, 0, time.UTC)
	zero := time.Time{}
	permanent := "permanent"
	stored := func(id uuid.UUID) *time.Time {
		return client.HRDetails.Query().Where(hrdetails.EmployeeID(id)).OnlyX(ctx).DateJoined
	}
	apply := func(id uuid.UUID, in HRInput) {
		t.Helper()
		if err := svc.UpsertHR(ctx, tenant, id, in); err != nil {
			t.Fatal(err)
		}
	}
	apply(emp.ID, HRInput{DateJoined: &joined})
	apply(emp.ID, HRInput{EmploymentType: &permanent})
	if got := stored(emp.ID); got == nil || !got.Equal(joined) {
		t.Fatalf("date joined = %v, want it kept when not sent", got)
	}
	apply(emp.ID, HRInput{DateJoined: &zero})
	if got := stored(emp.ID); got != nil {
		t.Fatalf("date joined = %v, want cleared", got)
	}
	if h := client.HRDetails.Query().Where(hrdetails.EmployeeID(emp.ID)).OnlyX(ctx); h.EmploymentType != permanent {
		t.Fatalf("clearing the date changed the employment type: %q", h.EmploymentType)
	}

	fresh := client.Employee.Create().SetTenantID(tenant).SetFirstName("B").SaveX(ctx)
	apply(fresh.ID, HRInput{DateJoined: &zero})
	if got := stored(fresh.ID); got != nil {
		t.Fatalf("new employee date joined = %v, want none", got)
	}
}
