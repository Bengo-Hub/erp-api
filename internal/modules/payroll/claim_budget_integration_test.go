package payroll

import (
	"context"
	"database/sql"
	"errors"
	"os"
	"strings"
	"testing"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

type fakeBudget struct {
	action string
	calls  int
	last   treasury.ClaimCheck
}

func (f *fakeBudget) CheckClaimBudget(_ context.Context, _ uuid.UUID, in treasury.ClaimCheck) treasury.BudgetResult {
	f.calls++
	f.last = in
	return treasury.BudgetResult{Action: f.action}
}

// Runs against Postgres when ERP_TEST_DATABASE_URL is set (a throwaway schema per run).
func TestIntegration_ApproveClaimBudgetCheck(t *testing.T) {
	url := os.Getenv("ERP_TEST_DATABASE_URL")
	if url == "" {
		t.Skip("ERP_TEST_DATABASE_URL not set")
	}
	admin, err := sql.Open("pgx", url)
	if err != nil {
		t.Fatal(err)
	}
	schema := "erp_claim_" + strings.ReplaceAll(uuid.NewString()[:8], "-", "")
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
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("E").SaveX(ctx)
	proj := uuid.New()
	claim := client.ExpenseClaim.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).
		SetAmount(decimal.RequireFromString("1500")).SetClaimType("general").SetProjectID(proj).SaveX(ctx)

	fb := &fakeBudget{action: "stop"}
	svc := NewService(client, nil).WithBudgetChecker(fb)
	var over *OverBudgetError
	if _, err := svc.ApproveClaim(ctx, tenant, claim.ID, uuid.New(), false); !errors.As(err, &over) {
		t.Fatalf("stop must block approval, got %v", err)
	}
	if fb.last.Amount != "1500.00" || fb.last.ProjectID == nil || *fb.last.ProjectID != proj.String() || fb.last.ClaimID != claim.ID.String() {
		t.Fatalf("check request = %+v", fb.last)
	}
	if got := client.ExpenseClaim.GetX(ctx, claim.ID); got.Approved {
		t.Fatal("a blocked claim must stay unapproved")
	}
	approved, err := svc.ApproveClaim(ctx, tenant, claim.ID, uuid.New(), true)
	if err != nil || !approved.Approved {
		t.Fatalf("override approves: %v %v", approved, err)
	}
	calls := fb.calls
	if _, err := svc.ApproveClaim(ctx, tenant, claim.ID, uuid.New(), false); err != nil || fb.calls != calls {
		t.Fatalf("re-approving is idempotent and does not re-check: %v (calls %d->%d)", err, calls, fb.calls)
	}
	fb.action = "warn"
	other := client.ExpenseClaim.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetAmount(decimal.RequireFromString("10")).SaveX(ctx)
	if _, err := svc.ApproveClaim(ctx, tenant, other.ID, uuid.New(), false); err != nil {
		t.Fatalf("warn approves: %v", err)
	}
}
