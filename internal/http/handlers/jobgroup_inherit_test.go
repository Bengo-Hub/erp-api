package handlers

import (
	"context"
	"net/http"
	"testing"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/modules/orgsettings"
)

// TestInheritedJobGroups: a company lists the platform's job groups without a copy, puts an
// employee in one (the employee list shows its title), changes its description and reverts it,
// cannot rename or delete it, and its own job group of the same title replaces the platform one.
func TestInheritedJobGroups(t *testing.T) {
	c := handlersTestClient(t)
	ctx := context.Background()
	system, tenant := uuid.New(), uuid.New()
	gradeA := c.JobGroup.Create().SetTenantID(system).SetTitle("Grade A").SetDescription("Entry").SaveX(ctx)
	gradeB := c.JobGroup.Create().SetTenantID(system).SetTitle("Grade B").SaveX(ctx)
	own := c.JobGroup.Create().SetTenantID(tenant).SetTitle("grade b ").SaveX(ctx)

	h := hrmRouter(tenant, NewOrgSettingsHandler(zap.NewNop(), orgsettings.NewService(c).WithSystemTenant(system)).RegisterRoutes)
	call := func(method, path, body string) (int, map[string]any) { return selfCall(h, method, path, body, tenant) }
	list := func() map[string]map[string]any {
		t.Helper()
		code, body := call(http.MethodGet, "/hrm/employees/job-groups/", "")
		_, rows := listTotal(t, body)
		if code != http.StatusOK {
			t.Fatalf("list: %d %v", code, body)
		}
		out := map[string]map[string]any{}
		for _, r := range rows {
			m := r.(map[string]any)
			out[m["id"].(string)] = m
		}
		return out
	}
	rows := list()
	if len(rows) != 2 || rows[gradeA.ID.String()]["inherited"] != true || rows[own.ID.String()]["inherited"] != false || rows[gradeB.ID.String()] != nil {
		t.Fatalf("list: %v", rows)
	}

	// An employee in a platform job group; the employee list shows its title.
	svc := employees.NewService(c).WithSystemTenant(system)
	emp := hrmEmployee(ctx, c, tenant, "Jane", "Wanjiru", "G-1")
	if _, err := svc.UpsertSalary(ctx, tenant, emp.ID, employees.SalaryInput{JobGroupID: &gradeA.ID}); err != nil {
		t.Fatalf("save with a platform job group: %v", err)
	}
	views, err := svc.Enrich(ctx, tenant, []*ent.Employee{c.Employee.GetX(ctx, emp.ID)})
	if err != nil || views[0].JobGroup == nil || views[0].JobGroup.Name != "Grade A" {
		t.Fatalf("employee view: %v %v", views, err)
	}
	// Another company's own job group is still refused.
	foreign := c.JobGroup.Create().SetTenantID(uuid.New()).SetTitle("X").SaveX(ctx)
	if err := svc.CheckSalary(ctx, tenant, employees.SalaryInput{JobGroupID: &foreign.ID}); err == nil {
		t.Fatal("another company's job group must be refused")
	}

	path := "/hrm/employees/job-groups/" + gradeA.ID.String()
	if code, b := call(http.MethodPut, path, `{"name":"Grade A","description":"Graduate entry"}`); code != http.StatusOK || b["description"] != "Graduate entry" || b["customised"] != true {
		t.Fatalf("customise: %d %v", code, b)
	}
	if d := c.JobGroup.GetX(ctx, gradeA.ID).Description; d == nil || *d != "Entry" {
		t.Fatalf("the platform row changed: %v", d)
	}
	if code, b := call(http.MethodPut, path, `{"name":"Grade Z"}`); code != http.StatusBadRequest {
		t.Fatalf("rename: %d %v", code, b)
	}
	if code, b := call(http.MethodDelete, path, ""); code != http.StatusBadRequest {
		t.Fatalf("delete: %d %v", code, b)
	}
	if code, b := call(http.MethodDelete, path+"/customisation", ""); code != http.StatusOK || b["description"] != "Entry" || b["customised"] != false {
		t.Fatalf("revert: %d %v", code, b)
	}
	if code, _ := call(http.MethodDelete, path+"/customisation", ""); code != http.StatusConflict {
		t.Fatalf("second revert: %d", code)
	}
	if n := c.JobGroup.Query().CountX(ctx); n != 4 {
		t.Fatalf("job groups copied: %d rows", n)
	}
}
