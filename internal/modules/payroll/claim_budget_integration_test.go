package payroll

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

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

func TestIntegration_ApproveClaimBudgetCheck(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
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
