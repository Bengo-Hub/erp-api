package performance

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
)

// TestReviewWorkflowOnPostgres: the review FSM the UI drives (start, submit for approval,
// reject with a reason, reopen), the status filter, and the reason saved as comments.
// Needs ERP_TEST_DATABASE_URL (a throwaway schema is created and dropped).
func TestReviewWorkflowOnPostgres(t *testing.T) {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_perf_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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

	tenant := uuid.New()
	svc := NewService(client)
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Jane").SetLastName("Wanjiru").SaveX(ctx)
	boss := client.Employee.Create().SetTenantID(tenant).SetFirstName("Peter").SetLastName("Otieno").SaveX(ctx)
	rv, err := svc.CreateReview(ctx, tenant, ReviewInput{EmployeeID: emp.ID, ReviewerID: &boss.ID, Title: "Q4", ReviewDate: time.Now()})
	if err != nil {
		t.Fatal(err)
	}
	views, err := svc.DescribeReviews(ctx, tenant, []*ent.PerformanceReview{rv})
	if err != nil || views[0].EmployeeName != "Jane Wanjiru" || views[0].ReviewerName != "Peter Otieno" {
		t.Fatalf("names: %v %+v", err, views)
	}
	if _, err := svc.SetReviewStatus(ctx, tenant, rv.ID, "submitted", "", ""); err == nil {
		t.Fatal("submitted is not a review status and must be refused")
	}
	for _, st := range []string{"in_progress", "completed"} {
		if _, err := svc.SetReviewStatus(ctx, tenant, rv.ID, st, "", ""); err != nil {
			t.Fatalf("%s: %v", st, err)
		}
	}
	pending, err := svc.ListReviews(ctx, tenant, nil, "completed")
	if err != nil || len(pending) != 1 {
		t.Fatalf("status filter: %v %d", err, len(pending))
	}
	if none, _ := svc.ListReviews(ctx, tenant, nil, "submitted"); len(none) != 0 {
		t.Fatalf("unknown status must match nothing, got %d", len(none))
	}
	got, err := svc.SetReviewStatus(ctx, tenant, rv.ID, "rejected", "", "Targets not evidenced")
	if err != nil {
		t.Fatal(err)
	}
	if got.Comments != "Targets not evidenced" {
		t.Fatalf("reason not saved: %q", got.Comments)
	}
	if _, err := svc.SetReviewStatus(ctx, tenant, rv.ID, "in_progress", "", ""); err != nil {
		t.Fatalf("reopen: %v", err)
	}
}
