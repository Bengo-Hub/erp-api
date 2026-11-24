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
)

// TestAttendanceRuleRotationOffDayUpdates: PUT and PATCH edit rules, rotations and off-days
// with the create validation, another tenant's row answers 404, and the list views carry
// employee and shift names.
func TestAttendanceRuleRotationOffDayUpdates(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant, other := uuid.New(), uuid.New()
	svc := attendance.NewService(client)
	h := hrmRouter(tenant, NewAttendanceHandler(zap.NewNop(), svc).RegisterRoutes)
	call := func(method, path, body string) (int, map[string]any) { return selfCall(h, method, path, body, tenant) }
	ho := hrmRouter(other, NewAttendanceHandler(zap.NewNop(), svc).RegisterRoutes)
	callOther := func(method, path, body string) (int, map[string]any) { return selfCall(ho, method, path, body, other) }

	// Rules.
	code, rule := call(http.MethodPost, "/hrm/attendance/rules", `{"name":"Grace","rule_type":"late_policy","late_threshold_minutes":10}`)
	if code != http.StatusCreated {
		t.Fatalf("create rule: %d %v", code, rule)
	}
	ruleID := rule["id"].(string)
	code, body := call(http.MethodPut, "/hrm/attendance/rules/"+ruleID,
		`{"name":"Overtime","rule_type":"overtime_policy","overtime_threshold_hours":"9","overtime_rate_multiplier":"1.5","is_active":false}`)
	// Ent's JSON omits a false bool, so an inactive rule has no is_active key; it must not be true.
	if code != http.StatusOK || body["name"] != "Overtime" || body["rule_type"] != "overtime_policy" || body["is_active"] == true {
		t.Fatalf("update rule: %d %v", code, body)
	}
	if code, body := call(http.MethodPatch, "/hrm/attendance/rules/"+ruleID, `{"name":"x","rule_type":"nope"}`); code != http.StatusBadRequest || body["error"] != "invalid value for rule type" {
		t.Fatalf("bad rule_type must be a readable 400, got %d %v", code, body)
	}
	if code, _ := call(http.MethodPut, "/hrm/attendance/rules/"+ruleID, `{"name":"x","rule_type":"late_policy","late_penalty_value":"-1"}`); code != http.StatusBadRequest {
		t.Fatalf("negative penalty must be refused, got %d", code)
	}
	if code, _ := callOther(http.MethodPut, "/hrm/attendance/rules/"+ruleID, `{"name":"x","rule_type":"late_policy"}`); code != http.StatusNotFound {
		t.Fatalf("other tenant's rule must be 404, got %d", code)
	}

	// Rotations.
	day := client.WorkShift.Create().SetTenantID(tenant).SetName("Day").SetStartTime("08:00").SetEndTime("17:00").SaveX(ctx)
	night := client.WorkShift.Create().SetTenantID(tenant).SetName("Night").SetStartTime("20:00").SetEndTime("05:00").SaveX(ctx)
	code, rot := call(http.MethodPost, "/hrm/attendance/rotations", fmt.Sprintf(`{"title":"Weekly","shift_ids":[%q],"run_duration":1,"run_unit":"Weeks"}`, day.ID))
	if code != http.StatusCreated {
		t.Fatalf("create rotation: %d %v", code, rot)
	}
	rotID := rot["id"].(string)
	code, body = call(http.MethodPut, "/hrm/attendance/rotations/"+rotID,
		fmt.Sprintf(`{"title":"Fortnightly","shift_ids":[%q,%q],"run_duration":2,"run_unit":"Weeks","break_duration":1,"break_unit":"Day"}`, day.ID, night.ID))
	if code != http.StatusOK || body["title"] != "Fortnightly" || body["run_duration"] != float64(2) {
		t.Fatalf("update rotation: %d %v", code, body)
	}
	if code, _ := callOther(http.MethodPatch, "/hrm/attendance/rotations/"+rotID, `{"title":"x"}`); code != http.StatusNotFound {
		t.Fatalf("other tenant's rotation must be 404, got %d", code)
	}
	_, list := call(http.MethodGet, "/hrm/attendance/rotations", "")
	if _, rows := listTotal(t, list); len(rows) != 1 || fmt.Sprint(rows[0].(map[string]any)["shift_names"]) != "[Day Night]" {
		t.Fatalf("rotation list must carry shift names in order: %v", list)
	}

	// Off days.
	jane := hrmEmployee(ctx, client, tenant, "Jane", "Wanjiru", "S-1001")
	peter := hrmEmployee(ctx, client, tenant, "Peter", "Otieno", "S-1002")
	code, off := call(http.MethodPost, "/hrm/attendance/off-days", fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-20","reason":"Family event"}`, jane.ID))
	if code != http.StatusCreated {
		t.Fatalf("create off-day: %d %v", code, off)
	}
	offID := off["id"].(string)
	code, body = call(http.MethodPut, "/hrm/attendance/off-days/"+offID, fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-21","reason":""}`, peter.ID))
	if code != http.StatusOK || body["employee_id"] != peter.ID.String() || body["reason"] != nil {
		t.Fatalf("update off-day: %d %v", code, body)
	}
	if code, _ := call(http.MethodPut, "/hrm/attendance/off-days/"+offID, `{"employee_id":"nope","date":"2026-11-21"}`); code != http.StatusBadRequest {
		t.Fatalf("bad employee_id must be 400, got %d", code)
	}
	if code, _ := callOther(http.MethodPut, "/hrm/attendance/off-days/"+offID, fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-21"}`, peter.ID)); code != http.StatusNotFound {
		t.Fatalf("other tenant's off-day must be 404, got %d", code)
	}
	_, list = call(http.MethodGet, "/hrm/attendance/off-days", "")
	if _, rows := listTotal(t, list); len(rows) != 1 || rows[0].(map[string]any)["employee_name"] != "Peter Otieno" {
		t.Fatalf("off-day list must carry the employee name: %v", list)
	}

	// Overrides written by the planner carry the shift hours and the planner marker.
	if _, err := svc.UpsertPlannerCell(ctx, tenant, attendance.PlannerCellInput{EmployeeID: jane.ID, Date: time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC), WorkShiftID: &night.ID}); err != nil {
		t.Fatal(err)
	}
	_, list = call(http.MethodGet, "/hrm/attendance/overrides", "")
	_, rows := listTotal(t, list)
	if len(rows) != 1 {
		t.Fatalf("overrides: %v", list)
	}
	o := rows[0].(map[string]any)
	if o["shift_name"] != "Night" || o["shift_start_time"] != "20:00" || o["shift_end_time"] != "05:00" ||
		o["from_planner"] != true || o["reason"] != attendance.PlannerReason || o["employee_name"] != "Jane Wanjiru" {
		t.Fatalf("planner override view: %v", o)
	}

	// Timesheets list carries the employee name.
	if code, body := call(http.MethodPost, "/hrm/attendance/timesheets", fmt.Sprintf(`{"employee_id":%q,"period_start":"2026-11-01","period_end":"2026-11-30"}`, jane.ID)); code != http.StatusCreated {
		t.Fatalf("create timesheet: %d %v", code, body)
	}
	_, list = call(http.MethodGet, "/hrm/attendance/timesheets", "")
	if _, rows := listTotal(t, list); len(rows) != 1 || rows[0].(map[string]any)["employee_name"] != "Jane Wanjiru" || rows[0].(map[string]any)["employee_number"] != "S-1001" {
		t.Fatalf("timesheet list must carry the employee name and number: %v", list)
	}
	_, list = call(http.MethodGet, "/hrm/attendance/timesheets?status=submitted", "")
	if total, _ := listTotal(t, list); total != 0 {
		t.Fatalf("approvals queue must hold only submitted timesheets: %v", list)
	}
}
