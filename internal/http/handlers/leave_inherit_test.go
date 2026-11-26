package handlers

import (
	"context"
	"net/http"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
)

// TestInheritedLeaveTypes: a company uses the platform's leave types without a copy, customises
// one (only the changed values are kept, the id stays the platform's), reverts it, replaces one by
// an own type of the same name, and accrual gives balances on the inherited types with the
// company's changes.
func TestInheritedLeaveTypes(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	system := uuid.New()
	e.svc.WithSystemTenant(system)
	hr := e.hr(e.tenant)
	annual := e.c.LeaveCategory.Create().SetTenantID(system).SetName("Annual Leave").SetDescription("Paid").
		SetDefaultAnnualDays(decimal.NewFromInt(21)).SetAllowCarryover(true).SetMaxCarryoverDays(decimal.NewFromInt(5)).SaveX(ctx)
	sick := e.c.LeaveCategory.Create().SetTenantID(system).SetName("Sick Leave").SetDefaultAnnualDays(decimal.NewFromInt(14)).SaveX(ctx)
	study := e.c.LeaveCategory.Create().SetTenantID(system).SetName("Study Leave").SetDefaultAnnualDays(decimal.NewFromInt(5)).SaveX(ctx)
	// The company already has its own Study Leave (other spacing and case): it replaces the platform one.
	ownStudy := e.c.LeaveCategory.Create().SetTenantID(e.tenant).SetName(" study leave").SetDefaultAnnualDays(decimal.NewFromInt(10)).SaveX(ctx)

	byID := func() map[string]map[string]any {
		t.Helper()
		code, list := hr(http.MethodGet, "/hrm/leave/categories", "")
		_, rows := listTotal(t, list)
		if code != http.StatusOK {
			t.Fatalf("list: %d %v", code, list)
		}
		out := map[string]map[string]any{}
		for _, r := range rows {
			m := r.(map[string]any)
			out[m["id"].(string)] = m
		}
		return out
	}
	rows := byID()
	if len(rows) != 3 || rows[annual.ID.String()]["inherited"] != true || rows[ownStudy.ID.String()]["inherited"] != false || rows[study.ID.String()] != nil {
		t.Fatalf("list: %v", rows)
	}

	// Customise: the form sends name, days and carry forward.
	path := "/hrm/leave/categories/" + annual.ID.String()
	code, b := hr(http.MethodPut, path, `{"name":"Annual Leave","max_days":"24","is_paid":true,"carry_forward":true}`)
	if code != http.StatusOK || b["id"] != annual.ID.String() || b["default_annual_days"] != "24" || b["max_carryover_days"] != "5" {
		t.Fatalf("customise: %d %v", code, b)
	}
	saved := e.c.AppSetting.Query().Where(appsetting.TenantID(e.tenant), appsetting.AppKey(leave.TypeOverridesKey)).OnlyX(ctx).Value
	if want := `{"` + annual.ID.String() + `":{"default_annual_days":"24"}}`; saved != want {
		t.Fatalf("only the changed value is kept: %s", saved)
	}
	if got := e.c.LeaveCategory.GetX(ctx, annual.ID); !got.DefaultAnnualDays.Equal(decimal.NewFromInt(21)) {
		t.Fatalf("the platform row changed: %v", got)
	}
	if rows = byID(); rows[annual.ID.String()]["customised"] != true || rows[annual.ID.String()]["default_annual_days"] != "24" {
		t.Fatalf("list after customise: %v", rows[annual.ID.String()])
	}
	// Another company still sees the platform values.
	_, olist := e.hr(uuid.New())(http.MethodGet, "/hrm/leave/categories", "")
	if _, orows := listTotal(t, olist); len(orows) != 3 {
		t.Fatalf("other company: %v", olist)
	}

	// Accrual: inherited types with the changes, the own type, no balance for the replaced one.
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "I-1")
	if code, b := hr(http.MethodPost, "/hrm/leave/accrue?year=2026", ""); code != http.StatusOK {
		t.Fatalf("accrue: %d %v", code, b)
	}
	got := map[uuid.UUID]string{}
	for _, bal := range e.c.LeaveBalance.Query().Where(leavebalance.EmployeeID(jane.ID), leavebalance.Year(2026)).AllX(ctx) {
		got[bal.CategoryID] = bal.DaysEntitled.String()
	}
	if len(got) != 3 || got[annual.ID] != "24" || got[sick.ID] != "14" || got[ownStudy.ID] != "10" {
		t.Fatalf("balances: %v", got)
	}
	n, err := e.svc.AccrueAllTenants(ctx, 2027)
	if err != nil || n != 3 {
		t.Fatalf("accrue all: %d %v", n, err)
	}

	// Revert: back to the platform values; a second revert has nothing to drop.
	if code, b := hr(http.MethodDelete, path+"/customisation", ""); code != http.StatusOK || b["default_annual_days"] != "21" {
		t.Fatalf("revert: %d %v", code, b)
	}
	if code, _ := hr(http.MethodDelete, path+"/customisation", ""); code != http.StatusConflict {
		t.Fatalf("second revert: %d", code)
	}
	if code, _ := hr(http.MethodDelete, "/hrm/leave/categories/"+study.ID.String()+"/customisation", ""); code != http.StatusNotFound {
		t.Fatalf("revert of a replaced platform type: %d", code)
	}
	// Switching an inherited type off is a customisation too.
	// (ent leaves is_active out of the JSON when it is false.)
	if code, b := hr(http.MethodPut, "/hrm/leave/categories/"+sick.ID.String(), `{"is_active":false}`); code != http.StatusOK || b["is_active"] == true || b["name"] != "Sick Leave" {
		t.Fatalf("switch off: %d %v", code, b)
	}
	// The list always sends is_active, false included.
	if rows = byID(); rows[sick.ID.String()]["is_active"] != false || rows[sick.ID.String()]["customised"] != true {
		t.Fatalf("list after switch off: %v", rows[sick.ID.String()])
	}
	// A switched-off type takes no new request; one filed before stays.
	if code, b := hr(http.MethodPost, leavePath, fileBody(jane.ID.String(), annual.ID, "2026-11-02", "2026-11-03")); code != http.StatusCreated {
		t.Fatalf("request on an active type: %d %v", code, b)
	}
	if code, b := hr(http.MethodPost, leavePath, fileBody(jane.ID.String(), sick.ID, "2026-11-09", "2026-11-10")); code != http.StatusBadRequest || b["error"] != leave.ErrInactiveCategory.Error() {
		t.Fatalf("request on a switched-off type: %d %v", code, b)
	}
	if code, _ := hr(http.MethodPut, path, `{"is_active":false}`); code != http.StatusOK {
		t.Fatalf("switch off annual: %d", code)
	}
	if n := e.c.LeaveRequest.Query().CountX(ctx); n != 1 {
		t.Fatalf("the request filed before was not kept: %d", n)
	}
}
