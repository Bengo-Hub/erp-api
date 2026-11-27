package handlers

import (
	"context"
	"fmt"
	"net/http"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/contracts"
	"github.com/Bengo-Hub/erp-api/internal/modules/orgsettings"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

// TestFormFieldsRoundTrip: the fields the forms had dropped for want of storage are saved and come
// back: a job title's code, a department's description, a job group's grade and salary range
// (own, and on an inherited one as a customisation), a contract's notes and a claim line's date.
func TestFormFieldsRoundTrip(t *testing.T) {
	c := handlersTestClient(t)
	ctx := context.Background()
	system, tenant := uuid.New(), uuid.New()
	platform := c.JobGroup.Create().SetTenantID(system).SetTitle("Grade A").
		SetMetadata(map[string]any{"grade": "A", "min_salary": "20000", "max_salary": "40000"}).SaveX(ctx)

	h := hrmRouter(tenant,
		NewOrgSettingsHandler(zap.NewNop(), orgsettings.NewService(c).WithSystemTenant(system)).RegisterRoutes,
		NewContractsHandler(zap.NewNop(), contracts.NewService(c)).RegisterRoutes,
		NewPayrollHandler(zap.NewNop(), payroll.NewService(c, nil), nil).RegisterRoutes,
	)
	call := func(method, path, body string) (int, map[string]any) { return selfCall(h, method, path, body, tenant) }
	do := func(what, method, path, body string, want int) map[string]any {
		t.Helper()
		code, b := call(method, path, body)
		if code != want {
			t.Fatalf("%s: %d %v", what, code, b)
		}
		return b
	}
	get := func(what, path, id string) map[string]any {
		t.Helper()
		return do(what, http.MethodGet, path+id, "", http.StatusOK)
	}

	// Job title code.
	jt := do("job title", http.MethodPost, "/hrm/employees/job-titles/", `{"name":"Cashier","code":"JT-07"}`, http.StatusCreated)
	if b := get("job title", "/hrm/employees/job-titles/", jt["id"].(string)); b["code"] != "JT-07" {
		t.Fatalf("job title code: %v", b)
	}
	do("job title edit", http.MethodPut, "/hrm/employees/job-titles/"+jt["id"].(string), `{"name":"Cashier","code":"JT-08"}`, http.StatusOK)
	if b := get("job title", "/hrm/employees/job-titles/", jt["id"].(string)); b["code"] != "JT-08" {
		t.Fatalf("job title code after edit: %v", b)
	}

	// Department description.
	d := do("department", http.MethodPost, "/hrm/departments/", `{"name":"Shop","code":"SH","description":"Runs the shop floor"}`, http.StatusCreated)
	if b := get("department", "/hrm/departments/", d["id"].(string)); b["description"] != "Runs the shop floor" || b["code"] != "SH" {
		t.Fatalf("department description: %v", b)
	}
	do("department edit", http.MethodPut, "/hrm/departments/"+d["id"].(string), `{"name":"Shop","description":"Front of house"}`, http.StatusOK)
	if b := get("department", "/hrm/departments/", d["id"].(string)); b["description"] != "Front of house" {
		t.Fatalf("department description after edit: %v", b)
	}

	// Own job group: grade and salary range; a range the wrong way round is refused.
	g := do("job group", http.MethodPost, "/hrm/employees/job-groups/", `{"name":"Grade K","grade":"K","min_salary":"30000","max_salary":"50000"}`, http.StatusCreated)
	if b := get("job group", "/hrm/employees/job-groups/", g["id"].(string)); b["grade"] != "K" || b["min_salary"] != "30000" || b["max_salary"] != "50000" {
		t.Fatalf("job group range: %v", b)
	}
	do("job group range reversed", http.MethodPut, "/hrm/employees/job-groups/"+g["id"].(string), `{"name":"Grade K","min_salary":"60000","max_salary":"50000"}`, http.StatusBadRequest)
	do("job group range bad number", http.MethodPut, "/hrm/employees/job-groups/"+g["id"].(string), `{"name":"Grade K","min_salary":"lots"}`, http.StatusBadRequest)

	// Inherited job group: the platform values show; a change is the company's own and reverts.
	path := "/hrm/employees/job-groups/" + platform.ID.String()
	if b := get("platform group", "/hrm/employees/job-groups/", platform.ID.String()); b["grade"] != "A" || b["max_salary"] != "40000" || b["inherited"] != true {
		t.Fatalf("platform group: %v", b)
	}
	if b := do("customise range", http.MethodPut, path, `{"name":"Grade A","max_salary":"45000"}`, http.StatusOK); b["max_salary"] != "45000" || b["grade"] != "A" || b["customised"] != true {
		t.Fatalf("customise range: %v", b)
	}
	if m := c.JobGroup.GetX(ctx, platform.ID).Metadata; m["max_salary"] != "40000" {
		t.Fatalf("the platform row changed: %v", m)
	}
	if b := do("revert", http.MethodDelete, path+"/customisation", "", http.StatusOK); b["max_salary"] != "40000" || b["customised"] != false {
		t.Fatalf("revert: %v", b)
	}

	// Contract notes.
	emp := hrmEmployee(ctx, c, tenant, "Jane", "Wanjiru", "F-1")
	ct := do("contract", http.MethodPost, "/hrm/contracts/", fmt.Sprintf(`{"employee":%q,"contract_start_date":"2026-01-01","salary":"50000","notes":"Probation six months"}`, emp.ID), http.StatusCreated)
	if b := get("contract", "/hrm/contracts/", ct["id"].(string)); b["notes"] != "Probation six months" {
		t.Fatalf("contract notes: %v", b)
	}
	do("contract edit", http.MethodPut, "/hrm/contracts/"+ct["id"].(string), `{"notes":"Confirmed"}`, http.StatusOK)
	if b := get("contract", "/hrm/contracts/", ct["id"].(string)); b["notes"] != "Confirmed" || b["salary"] != "50000" {
		t.Fatalf("contract notes after edit: %v", b)
	}

	// Claim line date.
	claim := c.ExpenseClaim.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetAmount(decimal.Zero).SaveX(ctx)
	items := "/hrm/payroll/claims/" + claim.ID.String() + "/items"
	if b := do("claim line", http.MethodPost, items, `{"expense_type":"tt","description":"Taxi","amount":"800","date":"2026-11-20"}`, http.StatusCreated); b["date"] != "2026-11-20" {
		t.Fatalf("claim line date: %v", b)
	}
	code, list := call(http.MethodGet, items, "")
	rows, _ := list["data"].([]any)
	if code != http.StatusOK || len(rows) != 1 || rows[0].(map[string]any)["date"] != "2026-11-20" {
		t.Fatalf("claim lines: %d %v", code, list)
	}
	do("claim line bad date", http.MethodPost, items, `{"expense_type":"tt","amount":"1","date":"20/11/2026"}`, http.StatusBadRequest)
}
