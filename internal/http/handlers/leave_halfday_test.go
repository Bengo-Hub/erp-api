package handlers

import (
	"context"
	"fmt"
	"net/http"
	"testing"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/leavelog"
)

func halfBody(emp string, cat uuid.UUID, from, to string, startHalf, endHalf bool) string {
	return fmt.Sprintf(`{"employee_id":%q,"category_id":%q,"start_date":%q,"end_date":%q,"start_half_day":%t,"end_half_day":%t}`,
		emp, cat, from, to, startHalf, endHalf)
}

// TestLeaveHalfDays: a request may start at midday on its first day or end at midday on its last;
// each half counts 0.5 of that day under the type's count mode, a day that does not count stays
// at nothing, and the morning and the afternoon of one day can be two requests.
// 2026-11-02 is a Monday.
func TestLeaveHalfDays(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	hr := e.hr(e.tenant)
	annual, maternity := e.category("Annual Leave"), e.category("Maternity Leave")
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "H-1")
	days := func(cat uuid.UUID, from, to, extra, want string) {
		t.Helper()
		code, b := hr(http.MethodGet, previewPath(jane.ID, cat, from, to)+extra, "")
		if code != http.StatusOK || b["days"] != want {
			t.Fatalf("%s to %s%s: want %s, got %d %v", from, to, extra, want, code, b)
		}
	}
	days(annual, "2026-11-02", "2026-11-06", "&start_half_day=true", "4.5")
	days(annual, "2026-11-02", "2026-11-06", "&start_half_day=true&end_half_day=true", "4")
	days(annual, "2026-11-02", "2026-11-02", "&end_half_day=true", "0.5")
	days(annual, "2026-11-02", "2026-11-02", "&start_half_day=true", "0.5")
	// Calendar days: the half still comes off.
	days(maternity, "2026-11-02", "2026-11-08", "&end_half_day=true", "6.5")
	// A half on a day that does not count (Saturday) takes nothing off.
	days(annual, "2026-11-07", "2026-11-09", "&start_half_day=true", "1")
	// One day cannot be only the morning and only the afternoon.
	if code, b := hr(http.MethodGet, previewPath(jane.ID, annual, "2026-11-02", "2026-11-02")+"&start_half_day=true&end_half_day=true", ""); code != http.StatusBadRequest {
		t.Fatalf("both halves of one day: %d %v", code, b)
	}

	// The morning of Tuesday, then its afternoon; a full day on it overlaps both.
	const leavePath = "/hrm/leave/requests"
	code, morning := hr(http.MethodPost, leavePath, halfBody(jane.ID.String(), annual, "2026-11-03", "2026-11-03", false, true))
	if code != http.StatusCreated || morning["days_requested"] != "0.5" || morning["end_half_day"] != true || morning["start_half_day"] != false {
		t.Fatalf("morning: %d %v", code, morning)
	}
	if code, b := hr(http.MethodPost, leavePath, halfBody(jane.ID.String(), annual, "2026-11-03", "2026-11-03", true, false)); code != http.StatusCreated || b["days_requested"] != "0.5" {
		t.Fatalf("afternoon: %d %v", code, b)
	}
	if code, b := hr(http.MethodPost, leavePath, halfBody(jane.ID.String(), annual, "2026-11-03", "2026-11-03", false, false)); code != http.StatusBadRequest {
		t.Fatalf("full day over two halves: %d %v", code, b)
	}
	// The list shows both flags, false included.
	code, list := hr(http.MethodGet, leavePath+"?employee_id="+jane.ID.String(), "")
	_, rows := listTotal(t, list)
	if code != http.StatusOK || len(rows) != 2 {
		t.Fatalf("list: %d %v", code, list)
	}
	for _, r := range rows {
		m := r.(map[string]any)
		if _, ok := m["start_half_day"]; !ok {
			t.Fatalf("list row without start_half_day: %v", m)
		}
	}
}

// TestEditPendingLeave: the requester or HR changes a pending request; the days and the balance
// check are counted again without the request's own old days; anyone else gets 404 and a decided
// request cannot be edited.
func TestEditPendingLeave(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	hr := e.hr(e.tenant)
	annual, sick := e.category("Annual Leave"), e.category("Sick Leave")
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "E-1")
	other := hrmEmployee(ctx, e.c, e.tenant, "Otieno", "Kamau", "E-2")
	e.balance(jane.ID, annual, 2026, 3, 0)
	self := e.staff(jane.ID)
	stranger := e.staff(other.ID)

	const leavePath = "/hrm/leave/requests"
	code, a := self(http.MethodPost, leavePath, halfBody("", annual, "2026-11-02", "2026-11-02", false, true))
	if code != http.StatusCreated {
		t.Fatalf("file a: %d %v", code, a)
	}
	code, b := self(http.MethodPost, leavePath, halfBody("", annual, "2026-11-03", "2026-11-03", false, true))
	if code != http.StatusCreated {
		t.Fatalf("file b: %d %v", code, b)
	}
	path := leavePath + "/" + a["id"].(string)

	// 2.5 days: 3 remaining less b's 0.5 pending leaves exactly 2.5 (a's own 0.5 is not counted).
	edit := halfBody("", annual, "2026-11-04", "2026-11-06", false, true)
	code, prev := self(http.MethodGet, previewPath(jane.ID, annual, "2026-11-04", "2026-11-06")+"&end_half_day=true&request_id="+a["id"].(string), "")
	if code != http.StatusOK || prev["days"] != "2.5" || prev["refused"] != false || prev["available_balance"] != "2.5" {
		t.Fatalf("edit preview: %d %v", code, prev)
	}
	if code, got := stranger(http.MethodPut, path, edit); code != http.StatusNotFound {
		t.Fatalf("someone else's request: %d %v", code, got)
	}
	code, got := self(http.MethodPut, path, edit)
	if code != http.StatusOK || got["days_requested"] != "2.5" || got["end_half_day"] != true || got["start_date"].(string)[:10] != "2026-11-04" || got["status"] != "pending" {
		t.Fatalf("own edit: %d %v", code, got)
	}
	// Over the balance: refused, nothing changed.
	if code, got := self(http.MethodPut, path, halfBody("", annual, "2026-11-04", "2026-11-06", false, false)); code != http.StatusBadRequest {
		t.Fatalf("edit over the balance: %d %v", code, got)
	}
	// Overlapping the other request: refused.
	if code, got := self(http.MethodPut, path, halfBody("", annual, "2026-11-03", "2026-11-03", false, false)); code != http.StatusBadRequest {
		t.Fatalf("edit onto b: %d %v", code, got)
	}
	// HR moves it to another type with a reason.
	code, got = hr(http.MethodPut, path, fmt.Sprintf(`{"category_id":%q,"start_date":"2026-11-09","end_date":"2026-11-09","reason":"Clinic"}`, sick))
	if code != http.StatusOK || got["category_id"] != sick.String() || got["days_requested"] != "1" || got["reason"] != "Clinic" || got["end_half_day"] != false {
		t.Fatalf("hr edit: %d %v", code, got)
	}
	if n := e.c.LeaveLog.Query().Where(leavelog.ActionEQ(leavelog.ActionUpdate)).CountX(ctx); n != 2 {
		t.Fatalf("edit log entries: %d", n)
	}
	// Decided: no more edits.
	if code, got := hr(http.MethodPost, leavePath+"/"+b["id"].(string)+"/approve", "{}"); code != http.StatusOK {
		t.Fatalf("approve b: %d %v", code, got)
	}
	if code, got := self(http.MethodPut, leavePath+"/"+b["id"].(string), halfBody("", annual, "2026-11-10", "2026-11-10", false, false)); code != http.StatusBadRequest {
		t.Fatalf("edit of an approved request: %d %v", code, got)
	}
}
