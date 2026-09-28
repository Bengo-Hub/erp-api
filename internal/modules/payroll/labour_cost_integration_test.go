package payroll

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

func TestIntegration_ProjectLabourCost(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	d := decimal.RequireFromString
	month := time.Date(2026, 8, 1, 0, 0, 0, 0, time.UTC)
	a := client.Employee.Create().SetTenantID(tenant).SetFirstName("A").SaveX(ctx)
	b := client.Employee.Create().SetTenantID(tenant).SetFirstName("B").SaveX(ctx)
	road, school := uuid.New(), uuid.New()
	client.EmployeeProjectAllocation.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetProjectID(road).SetAllocationPercent(d("60")).SaveX(ctx)
	client.EmployeeProjectAllocation.Create().SetTenantID(tenant).SetEmployeeID(b.ID).SetProjectID(school).SetAllocationPercent(d("100")).
		SetEndDate(time.Date(2026, 6, 30, 0, 0, 0, 0, time.UTC)).SaveX(ctx) // ended before August
	slip := func(emp uuid.UUID, at time.Time, gross string) {
		client.Payslip.Create().SetTenantID(tenant).SetEmployeeID(emp).SetPaymentPeriod(at).SetGrossPay(d(gross)).SaveX(ctx)
	}
	slip(a.ID, month.AddDate(0, 0, 24), "1000")
	slip(b.ID, month.AddDate(0, 0, 24), "500")
	slip(a.ID, month.AddDate(0, 1, 24), "9999") // September

	rep, err := NewService(client, nil).ProjectLabourCost(ctx, tenant, month)
	if err != nil {
		t.Fatal(err)
	}
	if rep.Month != "2026-08" || !rep.TotalGross.Equal(d("1500")) || len(rep.Projects) != 2 {
		t.Fatalf("report = %+v", rep)
	}
	top, rest := rep.Projects[0], rep.Projects[1]
	if top.ProjectID == nil || *top.ProjectID != road || !top.Amount.Equal(d("600")) || top.SharePct != 40 {
		t.Errorf("road = %+v, want 600 (40%%)", top)
	}
	if rest.ProjectID != nil || !rest.Amount.Equal(d("900")) || rest.SharePct != 60 {
		t.Errorf("unallocated = %+v, want 900 (60%%): A's remaining 40%% plus all of B, whose allocation ended", rest)
	}
}
