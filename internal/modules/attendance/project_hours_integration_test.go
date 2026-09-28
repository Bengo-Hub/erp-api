package attendance

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
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/timesheet"
)

// Runs against Postgres when ERP_TEST_DATABASE_URL is set (a throwaway schema per run).
func testClient(t *testing.T) *ent.Client {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	ctx := context.Background()
	schema := "erp_att_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	if _, err := admin.ExecContext(ctx, "CREATE SCHEMA "+schema); err != nil {
		t.Fatal(err)
	}
	t.Cleanup(func() {
		_, _ = admin.ExecContext(context.Background(), "DROP SCHEMA "+schema+" CASCADE")
		_ = admin.Close()
	})
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
	if err := client.Schema.Create(ctx); err != nil {
		t.Fatalf("schema: %v", err)
	}
	return client
}

func TestIntegration_ProjectHours(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	tenant, other := uuid.New(), uuid.New()
	p1, p2, idle := uuid.New(), uuid.New(), uuid.New()
	day := func(s string) time.Time { d, _ := time.Parse(time.DateOnly, s); return d }
	sheet := func(tid uuid.UUID, status timesheet.Status) uuid.UUID {
		ts, err := client.Timesheet.Create().SetTenantID(tid).SetEmployeeID(uuid.New()).
			SetPeriodStart(day("2026-09-01")).SetPeriodEnd(day("2026-09-30")).SetStatus(status).Save(ctx)
		if err != nil {
			t.Fatal(err)
		}
		return ts.ID
	}
	entry := func(tid, ts, project uuid.UUID, date, regular, overtime string) {
		if _, err := client.TimesheetEntry.Create().SetTenantID(tid).SetTimesheetID(ts).SetProjectID(project).
			SetDate(day(date)).SetRegularHours(decimal.RequireFromString(regular)).SetOvertimeHours(decimal.RequireFromString(overtime)).
			Save(ctx); err != nil {
			t.Fatal(err)
		}
	}
	approved := sheet(tenant, timesheet.StatusApproved)
	submitted := sheet(tenant, timesheet.StatusSubmitted)
	draft := sheet(tenant, timesheet.StatusDraft)
	entry(tenant, approved, p1, "2026-09-01", "8", "1.5")
	entry(tenant, approved, p1, "2026-09-02", "6", "0")
	entry(tenant, approved, p2, "2026-09-03", "4", "0")
	entry(tenant, approved, p1, "2026-10-05", "8", "0") // outside the window
	entry(tenant, submitted, p1, "2026-09-01", "3", "0")
	entry(tenant, draft, p1, "2026-09-01", "99", "0") // drafts never count
	otherSheet := sheet(other, timesheet.StatusApproved)
	entry(other, otherSheet, p1, "2026-09-01", "50", "0") // another tenant

	got, err := NewService(client).ProjectHours(ctx, tenant, []uuid.UUID{p1, p2, idle}, day("2026-09-01"), day("2026-09-30"))
	if err != nil {
		t.Fatal(err)
	}
	want := []struct{ approved, submitted string }{{"15.5", "3"}, {"4", "0"}, {"0", "0"}}
	for i, w := range want {
		if !got[i].ApprovedHours.Equal(decimal.RequireFromString(w.approved)) || !got[i].SubmittedHours.Equal(decimal.RequireFromString(w.submitted)) {
			t.Errorf("project %d = %s/%s, want %s/%s", i, got[i].ApprovedHours, got[i].SubmittedHours, w.approved, w.submitted)
		}
	}
	if _, err := NewService(client).ProjectHours(ctx, tenant, make([]uuid.UUID, MaxProjectHoursBatch+1), time.Time{}, time.Time{}); err == nil {
		t.Fatal("oversized batch must be refused")
	}
}
