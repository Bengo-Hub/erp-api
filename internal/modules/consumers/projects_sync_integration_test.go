package consumers

import (
	"context"
	"testing"
	"time"

	sharedevents "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
)

// A renamed project's name reaches its allocations, a closed project's allocations end on the
// closing day (an earlier end stays), and other tenants' and projects' allocations are untouched.
func TestIntegration_ProjectSync(t *testing.T) {
	client := consumersTestClient(t)
	ctx := context.Background()
	c := NewProjectSyncConsumer(zap.NewNop(), employees.NewService(client), nil)
	tenant, other, project := uuid.New(), uuid.New(), uuid.New()
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("A").SaveX(ctx)
	early := time.Date(2026, 9, 30, 0, 0, 0, 0, time.UTC)
	open := client.EmployeeProjectAllocation.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetProjectID(project).
		SetProjectName("Old").SetAllocationPercent(decimal.NewFromInt(50)).SaveX(ctx)
	ended := client.EmployeeProjectAllocation.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetProjectID(project).
		SetProjectName("Old").SetAllocationPercent(decimal.NewFromInt(10)).SetEndDate(early).SaveX(ctx)
	foreign := client.EmployeeProjectAllocation.Create().SetTenantID(other).SetEmployeeID(uuid.New()).SetProjectID(project).
		SetProjectName("Old").SetAllocationPercent(decimal.NewFromInt(50)).SaveX(ctx)

	upd := sharedevents.NewEvent("updated", "project", project, tenant, map[string]any{"id": project.String(), "tenant_id": tenant.String(), "name": "New name"})
	if err := c.handleUpdated(ctx, upd); err != nil {
		t.Fatal(err)
	}
	closed := sharedevents.NewEvent("closed", "project", project, tenant, map[string]any{"id": project.String(), "tenant_id": tenant.String()})
	closed.Timestamp = time.Date(2026, 11, 20, 14, 0, 0, 0, time.UTC)
	if err := c.handleEnded(ctx, closed); err != nil {
		t.Fatal(err)
	}

	o := client.EmployeeProjectAllocation.GetX(ctx, open.ID)
	if o.ProjectName != "New name" || o.EndDate == nil || !o.EndDate.Equal(time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)) {
		t.Errorf("open allocation = %q ending %v, want New name ending 2026-11-20", o.ProjectName, o.EndDate)
	}
	if e := client.EmployeeProjectAllocation.GetX(ctx, ended.ID); e.EndDate == nil || !e.EndDate.Equal(early) {
		t.Errorf("an earlier end date moved: %v", e.EndDate)
	}
	if f := client.EmployeeProjectAllocation.GetX(ctx, foreign.ID); f.ProjectName != "Old" || f.EndDate != nil {
		t.Errorf("another tenant's allocation changed: %q %v", f.ProjectName, f.EndDate)
	}
	if err := c.handleUpdated(ctx, sharedevents.NewEvent("updated", "project", uuid.Nil, uuid.Nil, map[string]any{})); err == nil {
		t.Error("an event without ids must fail")
	}
}
