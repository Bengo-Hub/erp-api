package handlers

import (
	"context"
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
)

// TestPublicHolidayEdits: PUT and PATCH edit a holiday with the create validation, a county
// holiday needs a county, a clash on the unique (date, county) index is a readable 400, and
// another tenant's row answers 404 on edit and delete.
func TestPublicHolidayEdits(t *testing.T) {
	client := handlersTestClient(t)
	tenant, other := uuid.New(), uuid.New()
	svc := leave.NewService(client, nil)
	h := hrmRouter(tenant, NewLeaveHandler(zap.NewNop(), svc).RegisterRoutes)
	call := func(method, path, body string) (int, map[string]any) { return selfCall(h, method, path, body, tenant) }
	ho := hrmRouter(other, NewLeaveHandler(zap.NewNop(), svc).RegisterRoutes)
	callOther := func(method, path, body string) (int, map[string]any) { return selfCall(ho, method, path, body, other) }

	code, hol := call(http.MethodPost, "/hrm/leave/holidays", `{"name":"Mashujaa Day","date":"2026-10-20"}`)
	if code != http.StatusCreated || hol["is_national"] != true {
		t.Fatalf("create holiday: %d %v", code, hol)
	}
	id := hol["id"].(string)
	if code, body := call(http.MethodPost, "/hrm/leave/holidays", `{"name":"  ","date":"2026-10-21"}`); code != http.StatusBadRequest || body["error"] != "name is required" {
		t.Fatalf("blank name must be a readable 400, got %d %v", code, body)
	}

	code, body := call(http.MethodPut, "/hrm/leave/holidays/"+id, `{"name":"Mombasa Day","date":"2026-10-21","is_national":false,"county":"Mombasa"}`)
	if code != http.StatusOK || body["name"] != "Mombasa Day" || body["county"] != "Mombasa" || body["is_national"] == true ||
		body["date"].(string)[:10] != "2026-10-21" {
		t.Fatalf("update holiday: %d %v", code, body)
	}
	if code, body := call(http.MethodPatch, "/hrm/leave/holidays/"+id, `{"name":"x","date":"2026-10-21","is_national":false}`); code != http.StatusBadRequest || body["error"] != "county is required for a county holiday" {
		t.Fatalf("county holiday without a county must be a readable 400, got %d %v", code, body)
	}
	if code, _ := call(http.MethodPut, "/hrm/leave/holidays/"+id, `{"name":"x","date":"20-10-2026"}`); code != http.StatusBadRequest {
		t.Fatalf("bad date must be 400, got %d", code)
	}

	// Back to national: the county is cleared.
	code, body = call(http.MethodPatch, "/hrm/leave/holidays/"+id, `{"name":"Mashujaa Day","date":"2026-10-20","is_national":true,"county":"Mombasa"}`)
	if code != http.StatusOK || body["county"] != nil || body["is_national"] != true {
		t.Fatalf("national holiday must drop its county: %d %v", code, body)
	}

	// Two county holidays on one date for the same county clash on the unique index.
	if code, body := call(http.MethodPost, "/hrm/leave/holidays", `{"name":"A","date":"2026-12-01","is_national":false,"county":"Kisumu"}`); code != http.StatusCreated {
		t.Fatalf("create county holiday: %d %v", code, body)
	}
	_, b2 := call(http.MethodPost, "/hrm/leave/holidays", `{"name":"B","date":"2026-12-02","is_national":false,"county":"Kisumu"}`)
	if code, body := call(http.MethodPut, "/hrm/leave/holidays/"+b2["id"].(string), `{"name":"B","date":"2026-12-01","is_national":false,"county":"Kisumu"}`); code != http.StatusBadRequest ||
		body["error"] != "A holiday for this county already falls on that date" {
		t.Fatalf("duplicate county holiday must be a readable 400, got %d %v", code, body)
	}

	// Another tenant can neither edit nor delete the row, nor see it.
	if code, _ := callOther(http.MethodPut, "/hrm/leave/holidays/"+id, `{"name":"x","date":"2026-10-20"}`); code != http.StatusNotFound {
		t.Fatalf("other tenant's holiday edit must be 404, got %d", code)
	}
	if code, _ := callOther(http.MethodDelete, "/hrm/leave/holidays/"+id, ""); code != http.StatusNotFound {
		t.Fatalf("other tenant's holiday delete must be 404, got %d", code)
	}
	_, list := callOther(http.MethodGet, "/hrm/leave/holidays", "")
	if total, _ := listTotal(t, list); total != 0 {
		t.Fatalf("other tenant must not see the holidays: %v", list)
	}

	_, list = call(http.MethodGet, "/hrm/leave/holidays?year=2026", "")
	if total, _ := listTotal(t, list); total != 3 {
		t.Fatalf("holiday list: %v", list)
	}
	if code, _ := call(http.MethodDelete, "/hrm/leave/holidays/"+id, ""); code != http.StatusNoContent {
		t.Fatalf("delete holiday: %d", code)
	}
	if code, _ := call(http.MethodDelete, "/hrm/leave/holidays/"+id, ""); code != http.StatusNotFound {
		t.Fatalf("second delete must be 404, got %d", code)
	}
}

// TestShiftOverrideEdits: PUT and PATCH edit an override with the create validation (times
// required unless off duty), a planner row stays editable and keeps its shift while it is a
// manual shift, deleting a planner row clears the planner cell, and another tenant's row
// answers 404.
func TestShiftOverrideEdits(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant, other := uuid.New(), uuid.New()
	svc := attendance.NewService(client)
	h := hrmRouter(tenant, NewAttendanceHandler(zap.NewNop(), svc).RegisterRoutes)
	call := func(method, path, body string) (int, map[string]any) { return selfCall(h, method, path, body, tenant) }
	ho := hrmRouter(other, NewAttendanceHandler(zap.NewNop(), svc).RegisterRoutes)
	callOther := func(method, path, body string) (int, map[string]any) { return selfCall(ho, method, path, body, other) }

	jane := hrmEmployee(ctx, client, tenant, "Jane", "Wanjiru", "S-2001")
	peter := hrmEmployee(ctx, client, tenant, "Peter", "Otieno", "S-2002")

	// Create follows the same rule.
	if code, body := call(http.MethodPost, "/hrm/attendance/overrides", fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-25","override_type":"manual_shift"}`, jane.ID)); code != http.StatusBadRequest ||
		body["error"] != "start and end times are required unless the override is off duty" {
		t.Fatalf("manual shift without times must be a readable 400, got %d %v", code, body)
	}
	code, ov := call(http.MethodPost, "/hrm/attendance/overrides", fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-25","override_type":"off_duty","reason":"Funeral"}`, jane.ID))
	if code != http.StatusCreated {
		t.Fatalf("create override: %d %v", code, ov)
	}
	id := ov["id"].(string)

	code, body := call(http.MethodPut, "/hrm/attendance/overrides/"+id,
		fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-26","override_type":"half_day","start_time":"08:00","end_time":"12:00","reason":"Clinic"}`, peter.ID))
	if code != http.StatusOK || body["employee_id"] != peter.ID.String() || body["override_type"] != "half_day" ||
		body["start_time"] != "08:00" || body["end_time"] != "12:00" || body["reason"] != "Clinic" || body["status"] != "approved" {
		t.Fatalf("update override: %d %v", code, body)
	}
	if code, body := call(http.MethodPatch, "/hrm/attendance/overrides/"+id,
		fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-26","override_type":"half_day","start_time":"08:00"}`, peter.ID)); code != http.StatusBadRequest ||
		body["error"] != "start and end times are required unless the override is off duty" {
		t.Fatalf("half day without an end time must be a readable 400, got %d %v", code, body)
	}
	if code, body := call(http.MethodPatch, "/hrm/attendance/overrides/"+id,
		fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-26","override_type":"holiday"}`, peter.ID)); code != http.StatusBadRequest ||
		body["error"] != "override type must be off duty, manual shift or half day" {
		t.Fatalf("bad override_type must be a readable 400, got %d %v", code, body)
	}
	if code, _ := call(http.MethodPatch, "/hrm/attendance/overrides/"+id,
		fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-26","override_type":"manual_shift","start_time":"8am","end_time":"12:00"}`, peter.ID)); code != http.StatusBadRequest {
		t.Fatalf("bad time must be 400, got %d", code)
	}
	// Off duty drops the times.
	code, body = call(http.MethodPatch, "/hrm/attendance/overrides/"+id,
		fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-26","override_type":"off_duty","start_time":"08:00","end_time":"12:00"}`, peter.ID))
	if code != http.StatusOK || body["start_time"] != nil || body["end_time"] != nil || body["reason"] != nil {
		t.Fatalf("off duty must carry no times: %d %v", code, body)
	}
	if code, _ := callOther(http.MethodPut, "/hrm/attendance/overrides/"+id,
		fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-26","override_type":"off_duty"}`, peter.ID)); code != http.StatusNotFound {
		t.Fatalf("other tenant's override edit must be 404, got %d", code)
	}
	if code, _ := callOther(http.MethodDelete, "/hrm/attendance/overrides/"+id, ""); code != http.StatusNotFound {
		t.Fatalf("other tenant's override delete must be 404, got %d", code)
	}

	// A planner cell is an override row: editing it as a manual shift keeps the shift, and
	// deleting it clears the cell.
	night := client.WorkShift.Create().SetTenantID(tenant).SetName("Night").SetStartTime("20:00").SetEndTime("05:00").SaveX(ctx)
	day := time.Date(2026, 11, 27, 0, 0, 0, 0, time.UTC)
	cell, err := svc.UpsertPlannerCell(ctx, tenant, attendance.PlannerCellInput{EmployeeID: jane.ID, Date: day, WorkShiftID: &night.ID})
	if err != nil {
		t.Fatal(err)
	}
	// Moving the other override onto Jane's planner day clashes on the unique index.
	if code, body := call(http.MethodPut, "/hrm/attendance/overrides/"+id,
		fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-27","override_type":"off_duty"}`, jane.ID)); code != http.StatusBadRequest ||
		body["error"] != "This employee already has a shift override on that date" {
		t.Fatalf("duplicate employee and date must be a readable 400, got %d %v", code, body)
	}
	code, body = call(http.MethodPatch, "/hrm/attendance/overrides/"+cell.ID.String(),
		fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-27","override_type":"manual_shift","reason":%q}`, jane.ID, attendance.PlannerReason))
	if code != http.StatusOK || body["work_shift_id"] != night.ID.String() {
		t.Fatalf("planner row edit must keep its shift: %d %v", code, body)
	}
	code, body = call(http.MethodPatch, "/hrm/attendance/overrides/"+cell.ID.String(),
		fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-27","override_type":"manual_shift","start_time":"21:00","end_time":"06:00","reason":%q}`, jane.ID, attendance.PlannerReason))
	if code != http.StatusOK || body["start_time"] != "21:00" {
		t.Fatalf("planner row edit with times: %d %v", code, body)
	}
	cells, err := svc.ResolvePlanner(ctx, tenant, day, day)
	if err != nil || len(cells) != 1 || cells[0].ShiftName != "Night" || cells[0].StartTime != "21:00" || cells[0].EndTime != "06:00" {
		t.Fatalf("planner must show the edited cell: %v %+v", err, cells)
	}
	if code, _ := call(http.MethodDelete, "/hrm/attendance/overrides/"+cell.ID.String(), ""); code != http.StatusNoContent {
		t.Fatalf("delete planner override: %d", code)
	}
	cells, err = svc.ResolvePlanner(ctx, tenant, day, day)
	if err != nil || len(cells) != 0 {
		t.Fatalf("deleting the override must clear the planner cell: %v %+v", err, cells)
	}
	if code, _ := call(http.MethodDelete, "/hrm/attendance/overrides/"+cell.ID.String(), ""); code != http.StatusNotFound {
		t.Fatalf("second delete must be 404, got %d", code)
	}
}
