package defaults

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
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisaltemplate"
	"github.com/Bengo-Hub/erp-api/internal/ent/goal"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobgroup"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
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
	schema := "erp_def_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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

// TestRemovedDefaultsStayRemoved: a tenant that renamed or deleted a default does not get it back
// on the next run, and a new tenant gets the full set once.
func TestRemovedDefaultsStayRemoved(t *testing.T) {
	c := testClient(t)
	ctx := context.Background()
	s := &Service{orm: c}
	tenant := uuid.New()
	ensure := func() {
		t.Helper()
		for _, f := range []func(context.Context, uuid.UUID) error{s.EnsureLeaveCategories, s.EnsureJobGroups, s.EnsureGoalLibrary, s.EnsureAppraisalTemplate} {
			if err := f(ctx, tenant); err != nil {
				t.Fatal(err)
			}
		}
	}
	ensure()
	if n := c.LeaveCategory.Query().Where(leavecategory.TenantID(tenant)).CountX(ctx); n != len(defaultLeaveCategories) {
		t.Fatalf("leave types: %d", n)
	}
	c.LeaveCategory.Update().Where(leavecategory.TenantID(tenant), leavecategory.Name("Annual Leave")).SetName("Annual").ExecX(ctx)
	c.LeaveCategory.Delete().Where(leavecategory.TenantID(tenant), leavecategory.Name("Study Leave")).ExecX(ctx)
	c.JobGroup.Delete().Where(jobgroup.TenantID(tenant), jobgroup.Title("Grade G")).ExecX(ctx)
	c.Goal.Delete().Where(goal.TenantID(tenant), goal.Title("Drive Innovation")).ExecX(ctx)
	c.AppraisalTemplate.Update().Where(appraisaltemplate.TenantID(tenant)).SetName("Our review").ExecX(ctx)
	ensure()
	for what, n := range map[string]int{
		"Annual Leave": c.LeaveCategory.Query().Where(leavecategory.TenantID(tenant), leavecategory.Name("Annual Leave")).CountX(ctx),
		"Study Leave":  c.LeaveCategory.Query().Where(leavecategory.TenantID(tenant), leavecategory.Name("Study Leave")).CountX(ctx),
		"Grade G":      c.JobGroup.Query().Where(jobgroup.TenantID(tenant), jobgroup.Title("Grade G")).CountX(ctx),
		"goal":         c.Goal.Query().Where(goal.TenantID(tenant), goal.Title("Drive Innovation")).CountX(ctx),
		"template":     c.AppraisalTemplate.Query().Where(appraisaltemplate.TenantID(tenant)).CountX(ctx) - 1,
	} {
		if n != 0 {
			t.Errorf("%s came back on the second run", what)
		}
	}
}
