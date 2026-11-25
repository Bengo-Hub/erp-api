package handlers

import (
	"context"
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
	"github.com/Bengo-Hub/erp-api/internal/modules/fx"
	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
)

// TestBodyIDsMustBelongToTheTenant: an employee, shift, roster or leave type of another company in
// a request body answers 404 and saves nothing.
func TestBodyIDsMustBelongToTheTenant(t *testing.T) {
	c := handlersTestClient(t)
	ctx := context.Background()
	a, b := uuid.New(), uuid.New()
	att := attendance.NewService(c)
	h := hrmRouter(a, NewAttendanceHandler(zap.NewNop(), att).RegisterRoutes,
		NewLeaveHandler(zap.NewNop(), leave.NewService(c, nil)).RegisterRoutes,
		NewFXHandler(zap.NewNop(), fx.NewService(c, zap.NewNop())).RegisterRoutes)
	call := func(method, path, body string) (int, map[string]any) {
		return selfCall(h, method, path, body, uuid.Nil)
	}
	mine, theirs := hrmEmployee(ctx, c, a, "Jane", "Wanjiru", "A-1").ID, hrmEmployee(ctx, c, b, "Ben", "Otieno", "B-1").ID
	myShift := c.WorkShift.Create().SetTenantID(a).SetName("Day").SaveX(ctx).ID
	theirShift := c.WorkShift.Create().SetTenantID(b).SetName("Day").SaveX(ctx).ID
	start := time.Date(2026, 11, 2, 0, 0, 0, 0, time.UTC)
	myRoster := c.ShiftRoster.Create().SetTenantID(a).SetName("R").SetStartDate(start).SaveX(ctx).ID
	theirRoster := c.ShiftRoster.Create().SetTenantID(b).SetName("R").SetStartDate(start).SaveX(ctx).ID
	myCat := c.LeaveCategory.Create().SetTenantID(a).SetName("Annual").SaveX(ctx).ID
	theirCat := c.LeaveCategory.Create().SetTenantID(b).SetName("Secret type").SaveX(ctx).ID

	override := func(e uuid.UUID) string {
		return fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-25","override_type":"off_duty"}`, e)
	}
	cell := func(e, s uuid.UUID) string {
		return fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-26","work_shift_id":%q}`, e, s)
	}
	offDay := func(e uuid.UUID) string { return fmt.Sprintf(`{"employee_id":%q,"date":"2026-11-27"}`, e) }
	assign := func(e, r uuid.UUID) string {
		return fmt.Sprintf(`{"employee_id":%q,"roster_id":%q,"start_date":"2026-11-02"}`, e, r)
	}
	slot := func(e uuid.UUID) string { return fmt.Sprintf(`{"employee_id":%q,"cycle_day":1,"is_off_day":true}`, e) }
	ent := func(e, cat uuid.UUID) string {
		return fmt.Sprintf(`{"employee_id":%q,"category_id":%q,"year":2026,"days_entitled":"10"}`, e, cat)
	}
	const att0 = "/hrm/attendance"
	for _, tc := range []struct{ what, method, path, body string }{
		{"override", http.MethodPost, att0 + "/overrides", override(theirs)},
		{"planner cell employee", http.MethodPut, att0 + "/shift-planner/cell", cell(theirs, myShift)},
		{"planner cell shift", http.MethodPut, att0 + "/shift-planner/cell", cell(mine, theirShift)},
		{"off day", http.MethodPost, att0 + "/off-days", offDay(theirs)},
		{"assignment employee", http.MethodPost, att0 + "/assignments", assign(theirs, myRoster)},
		{"assignment roster", http.MethodPost, att0 + "/assignments", assign(mine, theirRoster)},
		{"slot employee", http.MethodPut, att0 + "/rosters/" + myRoster.String() + "/slots", slot(theirs)},
		{"slot roster", http.MethodPut, att0 + "/rosters/" + theirRoster.String() + "/slots", slot(mine)},
		{"entitlement employee", http.MethodPost, "/hrm/leave/entitlements", ent(theirs, myCat)},
	} {
		if code, body := call(tc.method, tc.path, tc.body); code != http.StatusNotFound {
			t.Errorf("%s: want 404, got %d %v", tc.what, code, body)
		}
	}
	if code, body := call(http.MethodPost, "/hrm/leave/entitlements", ent(mine, theirCat)); code != http.StatusBadRequest || body["error"] != leave.ErrUnknownCategory.Error() {
		t.Errorf("entitlement leave type: %d %v", code, body)
	}
	if n := c.StaffShiftOverride.Query().CountX(ctx) + c.OffDay.Query().CountX(ctx) + c.ShiftAssignment.Query().CountX(ctx) +
		c.ShiftRosterSlot.Query().CountX(ctx) + c.LeaveEntitlement.Query().CountX(ctx); n != 0 {
		t.Errorf("refused bodies saved %d rows", n)
	}

	// The tenant's own ids work, and an edit cannot move a row to another company's employee.
	_, ov := call(http.MethodPost, att0+"/overrides", override(mine))
	_, od := call(http.MethodPost, att0+"/off-days", offDay(mine))
	for what, code := range map[string]int{
		"cell":       first(call(http.MethodPut, att0+"/shift-planner/cell", cell(mine, myShift))),
		"assignment": first(call(http.MethodPost, att0+"/assignments", assign(mine, myRoster))),
		"slot":       first(call(http.MethodPut, att0+"/rosters/"+myRoster.String()+"/slots", slot(mine))),
		"ent":        first(call(http.MethodPost, "/hrm/leave/entitlements", ent(mine, myCat))),
	} {
		if code >= 300 {
			t.Errorf("own %s: %d", what, code)
		}
	}
	if code, body := call(http.MethodPut, att0+"/overrides/"+ov["id"].(string), override(theirs)); code != http.StatusNotFound {
		t.Errorf("moving an override: %d %v", code, body)
	}
	if code, body := call(http.MethodPut, att0+"/off-days/"+od["id"].(string), offDay(theirs)); code != http.StatusNotFound {
		t.Errorf("moving an off day: %d %v", code, body)
	}

	// Names are not read across companies, even from a row that already points there.
	c.LeaveRequest.Create().SetTenantID(a).SetEmployeeID(mine).SetCategoryID(theirCat).SetStartDate(start).SetEndDate(start).SetDaysRequested(decimal.NewFromInt(1)).SaveX(ctx)
	_, list := call(http.MethodGet, "/hrm/leave/requests?from=2026-11-01&to=2026-11-30", "")
	if _, rows := listTotal(t, list); len(rows) != 1 || rows[0].(map[string]any)["leave_category_name"] != "" {
		t.Errorf("another company's leave type name leaked: %v", list)
	}

	// Exchange rates: the platform's and the tenant's own.
	for _, tn := range []*uuid.UUID{nil, &a, &b} {
		c.ExchangeRate.Create().SetNillableTenantID(tn).SetBaseCurrency("KES").SetQuoteCurrency("USD").SetRate(decimal.NewFromInt(1)).SetRateDate(start).SaveX(ctx)
	}
	_, list = call(http.MethodGet, "/fx/rates?base=KES", "")
	if total, _ := listTotal(t, list); total != 2 {
		t.Errorf("rates: %v", list)
	}
}

func first(code int, _ map[string]any) int { return code }
