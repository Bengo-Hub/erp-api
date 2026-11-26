package handlers

import (
	"context"
	"net/http"
	"testing"

	"github.com/google/uuid"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// TestPlatformHolidaysForCompanies: every company sees the platform's national holidays without a
// copy, its leave counts skip them, it can switch one off (and back on) for itself only, it cannot
// edit or delete them, and only the platform owner manages the platform list.
func TestPlatformHolidaysForCompanies(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	system := uuid.New()
	e.svc.WithSystemTenant(system)
	e.svc.SetCalendar(attendance.NewService(e.c).WithSystemTenant(system))
	hr := e.hr(e.tenant)
	annual := e.category("Annual Leave")
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "P-1")

	// 2026-11-02 is a Monday; the platform holiday is on Tuesday.
	plat := e.c.PublicHoliday.Create().SetTenantID(system).SetName("National Day").SetDate(ymd("2026-11-03")).SaveX(ctx)
	days := func() any {
		t.Helper()
		code, b := hr(http.MethodGet, previewPath(jane.ID, annual, "2026-11-02", "2026-11-06"), "")
		if code != http.StatusOK {
			t.Fatalf("preview: %d %v", code, b)
		}
		return b["days"]
	}
	if got := days(); got != "4" {
		t.Fatalf("inherited holiday not skipped: %v", got)
	}
	code, list := hr(http.MethodGet, "/hrm/leave/holidays?year=2026", "")
	total, rows := listTotal(t, list)
	if code != http.StatusOK || total != 1 {
		t.Fatalf("list: %d %v", code, list)
	}
	if row := rows[0].(map[string]any); row["inherited"] != true || row["active"] != true || row["name"] != "National Day" {
		t.Fatalf("inherited row: %v", row)
	}
	if n := e.c.PublicHoliday.Query().CountX(ctx); n != 1 {
		t.Fatalf("platform holiday copied: %d rows", n)
	}

	// The company cannot edit or delete it, only switch it.
	path := "/hrm/leave/holidays/" + plat.ID.String()
	if code, _ := hr(http.MethodPut, path, `{"name":"x","date":"2026-11-03"}`); code != http.StatusNotFound {
		t.Fatalf("edit platform holiday: %d", code)
	}
	if code, _ := hr(http.MethodDelete, path, ""); code != http.StatusNotFound {
		t.Fatalf("delete platform holiday: %d", code)
	}
	if code, b := hr(http.MethodPut, path+"/active", `{}`); code != http.StatusBadRequest {
		t.Fatalf("switch without active: %d %v", code, b)
	}
	if code, b := hr(http.MethodPut, path+"/active", `{"active":false}`); code != http.StatusOK || b["active"] != false {
		t.Fatalf("switch off: %d %v", code, b)
	}
	if got := days(); got != "5" {
		t.Fatalf("switched-off holiday still skipped: %v", got)
	}
	if _, list := hr(http.MethodGet, "/hrm/leave/holidays?year=2026", ""); list["data"].([]any)[0].(map[string]any)["active"] != false {
		t.Fatalf("list after switch off: %v", list)
	}
	// Another company still has it.
	other := uuid.New()
	_, olist := e.hr(other)(http.MethodGet, "/hrm/leave/holidays?year=2026", "")
	if _, rows := listTotal(t, olist); len(rows) != 1 || rows[0].(map[string]any)["active"] != true {
		t.Fatalf("other company: %v", olist)
	}
	if code, b := hr(http.MethodPut, path+"/active", `{"active":true}`); code != http.StatusOK || b["active"] != true {
		t.Fatalf("switch on: %d %v", code, b)
	}
	if got := days(); got != "4" {
		t.Fatalf("switched back on: %v", got)
	}
	// The company's own holiday is not switched.
	own := e.c.PublicHoliday.Create().SetTenantID(e.tenant).SetName("Company Day").SetDate(ymd("2026-11-05")).SaveX(ctx)
	if code, _ := hr(http.MethodPut, "/hrm/leave/holidays/"+own.ID.String()+"/active", `{"active":false}`); code != http.StatusNotFound {
		t.Fatalf("own holiday switch: %d", code)
	}

	// scope=platform: the platform owner edits the platform list; anyone else gets their own.
	ownerClaims := &authclient.Claims{TenantID: e.tenant.String(), IsPlatformOwner: true}
	ownerClaims.Subject = uuid.NewString()
	owner := e.as(ownerClaims)
	if code, b := owner(http.MethodPut, path+"?scope=platform", `{"name":"National Day","date":"2026-11-04"}`); code != http.StatusOK || b["date"].(string)[:10] != "2026-11-04" {
		t.Fatalf("owner edits platform holiday: %d %v", code, b)
	}
	if code, _ := hr(http.MethodPut, path+"?scope=platform", `{"name":"x","date":"2026-11-03"}`); code != http.StatusNotFound {
		t.Fatalf("non-owner with scope=platform: %d", code)
	}
	if code, b := owner(http.MethodPost, "/hrm/leave/holidays?scope=platform", `{"name":"Second","date":"2026-11-04"}`); code != http.StatusBadRequest {
		t.Fatalf("two platform holidays on one national date: %d %v", code, b)
	}
}
