package handlers

import (
	"context"
	"net/http"
	"strings"
	"sync"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalworkflow"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
)

const leavePath = "/hrm/leave/requests"

func (e *leaveEnv) balance(emp, cat uuid.UUID, year int, entitled, taken int64) {
	e.c.LeaveBalance.Create().SetTenantID(e.tenant).SetEmployeeID(emp).SetCategoryID(cat).SetYear(year).
		SetDaysEntitled(decimal.NewFromInt(entitled)).SetDaysTaken(decimal.NewFromInt(taken)).
		SetDaysRemaining(decimal.NewFromInt(entitled - taken)).SaveX(context.Background())
}

// TestLeaveBalanceRule: paid types refuse and unpaid types allow by default, HR changes it per
// type, no balance row is no limit, pending requests of the type and year count, and approval
// checks again. Weeks in November 2026 and 2027 below are Monday to Friday, 5 working days.
func TestLeaveBalanceRule(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	hr := e.hr(e.tenant)
	annual := e.category("Annual Leave")
	unpaid := e.c.LeaveCategory.Create().SetTenantID(e.tenant).SetName("Unpaid Leave").SetIsPaid(false).SaveX(ctx).ID
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "L-1")
	js := e.staff(jane.ID)

	// No balance row: allowed, with nothing to warn about but the missing balance.
	code, b := js(http.MethodGet, previewPath(jane.ID, annual, "2027-11-01", "2027-11-05"), "")
	if code != http.StatusOK || b["refused"] != false || b["remaining_balance"] != nil || b["available_balance"] != nil || b["balance_rule"] != "refuse" {
		t.Fatalf("no balance: %d %v", code, b)
	}
	if code, b := js(http.MethodPost, leavePath, fileBody("", annual, "2027-11-01", "2027-11-05")); code != http.StatusCreated {
		t.Fatalf("no balance must be allowed: %d %v", code, b)
	}

	// Seven days left: the first week fits, the second does not while the first is pending.
	e.balance(jane.ID, annual, 2026, 10, 3)
	code, first := js(http.MethodPost, leavePath, fileBody("", annual, "2026-11-02", "2026-11-06"))
	if code != http.StatusCreated {
		t.Fatalf("within balance: %d %v", code, first)
	}
	code, b = js(http.MethodGet, previewPath(jane.ID, annual, "2026-11-09", "2026-11-13"), "")
	if code != http.StatusOK || b["refused"] != true || b["pending_days"] != "5" || b["available_balance"] != "2" || b["remaining_balance"] != "7" ||
		b["balance_message"] != "this request takes 5 days of Annual Leave but only 2 of the 2026 balance are available (7 remaining, 5 already in pending requests)" {
		t.Fatalf("preview over balance: %d %v", code, b)
	}
	if code, r := js(http.MethodPost, leavePath, fileBody("", annual, "2026-11-09", "2026-11-13")); code != http.StatusBadRequest || r["error"] != b["balance_message"] {
		t.Fatalf("over balance must be refused with the reason: %d %v", code, r)
	}
	// HR is bound by the rule too; exactly the available days is fine.
	if code, _ := hr(http.MethodPost, leavePath, fileBody(jane.ID.String(), annual, "2026-11-09", "2026-11-13")); code != http.StatusBadRequest {
		t.Fatalf("HR filing over balance: %d", code)
	}
	if code, r := js(http.MethodPost, leavePath, fileBody("", annual, "2026-11-09", "2026-11-10")); code != http.StatusCreated {
		t.Fatalf("exactly the balance: %d %v", code, r)
	}
	// Another type, and another year, have their own balance.
	if code, r := js(http.MethodGet, previewPath(jane.ID, annual, "2027-11-08", "2027-11-12"), ""); code != http.StatusOK || r["refused"] != false {
		t.Fatalf("other year: %d %v", code, r)
	}

	// Unpaid allows with a warning, even at zero.
	e.balance(jane.ID, unpaid, 2026, 0, 0)
	code, b = js(http.MethodGet, previewPath(jane.ID, unpaid, "2026-11-16", "2026-11-20"), "")
	if code != http.StatusOK || b["refused"] != false || b["balance_rule"] != "allow" || b["balance_message"] == nil {
		t.Fatalf("unpaid preview: %d %v", code, b)
	}
	code, over := js(http.MethodPost, leavePath, fileBody("", unpaid, "2026-11-16", "2026-11-20"))
	if code != http.StatusCreated {
		t.Fatalf("unpaid over balance: %d %v", code, over)
	}
	// HR changes the rule: the pending request is now refused at approval, and stays pending.
	set := func(cat uuid.UUID, rule string) {
		t.Helper()
		if code, b := hr(http.MethodPut, "/hrm/leave/categories/"+cat.String()+"/balance-rule", `{"balance_rule":"`+rule+`"}`); code != http.StatusOK || b["balance_rule"] != rule || b["count_mode"] != "working_days" {
			t.Fatalf("set rule: %d %v", code, b)
		}
	}
	set(unpaid, "refuse")
	overID := over["id"].(string)
	code, b = hr(http.MethodPost, leavePath+"/"+overID+"/approve", "{}")
	if msg, _ := b["error"].(string); code != http.StatusBadRequest || !strings.HasPrefix(msg, "this request takes 5 days of Unpaid Leave but only 0") {
		t.Fatalf("approval over balance: %d %v", code, b)
	}
	if st := e.c.LeaveRequest.GetX(ctx, uuid.MustParse(overID)).Status; st != leaverequest.StatusPending {
		t.Fatalf("refused approval must leave it pending, got %s", st)
	}
	set(unpaid, "allow")
	if code, b := hr(http.MethodPost, leavePath+"/"+overID+"/approve", "{}"); code != http.StatusOK {
		t.Fatalf("approval once allowed: %d %v", code, b)
	}
	set(annual, "allow")
	if code, b := js(http.MethodGet, previewPath(jane.ID, annual, "2026-11-23", "2026-11-27"), ""); code != http.StatusOK || b["refused"] != false || b["balance_message"] == nil {
		t.Fatalf("allowed paid type warns: %d %v", code, b)
	}
	set(annual, "refuse")

	if code, _ := hr(http.MethodPut, "/hrm/leave/categories/"+annual.String()+"/balance-rule", `{"balance_rule":"maybe"}`); code != http.StatusBadRequest {
		t.Fatalf("bad rule: %d", code)
	}
	if code, _ := js(http.MethodPut, "/hrm/leave/categories/"+annual.String()+"/balance-rule", `{"balance_rule":"allow"}`); code != http.StatusForbidden {
		t.Fatalf("staff must not change the rule: %d", code)
	}
	if code, _ := e.hr(uuid.New())(http.MethodPut, "/hrm/leave/categories/"+annual.String()+"/balance-rule", `{"balance_rule":"allow"}`); code != http.StatusNotFound {
		t.Fatalf("another tenant's type: %d", code)
	}

	// Approving the pending requests that fit is not blocked by each other.
	if code, b := hr(http.MethodPost, leavePath+"/"+first["id"].(string)+"/approve", "{}"); code != http.StatusOK {
		t.Fatalf("approve within balance: %d %v", code, b)
	}
}

// TestLeaveApprovalsQueueOnBalance: two pending requests that exceed the balance together (filed
// while the type allowed it) cannot both be approved at once.
func TestLeaveApprovalsQueueOnBalance(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	hr := e.hr(e.tenant)
	annual := e.category("Annual Leave")
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "L-1")
	e.balance(jane.ID, annual, 2026, 7, 0)
	var ids []string
	for _, d := range [][2]string{{"2026-11-02", "2026-11-06"}, {"2026-11-09", "2026-11-13"}} {
		row := e.c.LeaveRequest.Create().SetTenantID(e.tenant).SetEmployeeID(jane.ID).SetCategoryID(annual).
			SetStartDate(ymd(d[0])).SetEndDate(ymd(d[1])).SetDaysRequested(decimal.NewFromInt(5)).SaveX(ctx)
		ids = append(ids, row.ID.String())
	}
	var wg sync.WaitGroup
	codes := make([]int, 2)
	for i := range ids {
		wg.Add(1)
		go func() {
			defer wg.Done()
			codes[i], _ = hr(http.MethodPost, leavePath+"/"+ids[i]+"/approve", "{}")
		}()
	}
	wg.Wait()
	if codes[0]+codes[1] != http.StatusOK+http.StatusBadRequest {
		t.Fatalf("one must be approved and one refused: %v", codes)
	}
	bal := e.c.LeaveBalance.Query().Where(leavebalance.EmployeeID(jane.ID)).OnlyX(ctx)
	if !bal.DaysRemaining.Equal(decimal.NewFromInt(2)) {
		t.Fatalf("remaining: %s", bal.DaysRemaining)
	}
}

// TestLeaveGenericApprovals: decisions on the approvals screen apply to the leave, once, with the
// balance and self-approval refusals.
func TestLeaveGenericApprovals(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	hr := e.hr(e.tenant)
	annual := e.category("Annual Leave")
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "L-1")
	js := e.staff(jane.ID)
	e.balance(jane.ID, annual, 2026, 20, 0)
	wf := e.c.ApprovalWorkflow.Create().SetTenantID(e.tenant).SetModule(approvalworkflow.ModuleLeaveRequest).SetName("Leave").SaveX(ctx)
	for i := 1; i <= 2; i++ {
		e.c.ApprovalWorkflowStep.Create().SetTenantID(e.tenant).SetWorkflowID(wf.ID).SetSequence(i).SetName("Step").SaveX(ctx)
	}
	file := func(from, to string) (uuid.UUID, string) {
		t.Helper()
		code, b := js(http.MethodPost, leavePath, fileBody("", annual, from, to))
		if code != http.StatusCreated {
			t.Fatalf("file: %d %v", code, b)
		}
		id := uuid.MustParse(b["id"].(string))
		ar := e.c.ApprovalRequest.Query().Where(approvalrequest.ObjectID(id)).OnlyX(ctx)
		return id, "/approvals/requests/" + ar.ID.String()
	}
	status := func(id uuid.UUID) leaverequest.Status { return e.c.LeaveRequest.GetX(ctx, id).Status }
	taken := func() string {
		return e.c.LeaveBalance.Query().Where(leavebalance.EmployeeID(jane.ID)).OnlyX(ctx).DaysTaken.String()
	}

	id, ap := file("2026-11-02", "2026-11-06")
	if code, b := hr(http.MethodPost, ap+"/approve", "{}"); code != http.StatusOK || status(id) != leaverequest.StatusPending {
		t.Fatalf("first step: %d %v %s", code, b, status(id))
	}
	code, b := hr(http.MethodPost, ap+"/approve", "{}")
	if code != http.StatusOK || b["apply_error"] != nil || status(id) != leaverequest.StatusApproved || taken() != "5" {
		t.Fatalf("last step must approve the leave: %d %v %s %s", code, b, status(id), taken())
	}
	// Deciding again changes nothing.
	if code, _ := hr(http.MethodPost, ap+"/approve", "{}"); code != http.StatusBadRequest || taken() != "5" {
		t.Fatalf("a second decision must be refused: %d %s", code, taken())
	}

	// Rejection carries the comment.
	id, ap = file("2026-11-09", "2026-11-13")
	if code, b := hr(http.MethodPost, ap+"/reject", `{"comment":"Stock take"}`); code != http.StatusOK || b["apply_error"] != nil {
		t.Fatalf("reject: %d %v", code, b)
	}
	if row := e.c.LeaveRequest.GetX(ctx, id); row.Status != leaverequest.StatusRejected || row.RejectionReason != "Stock take" || taken() != "5" {
		t.Fatalf("rejected leave: %v", row)
	}

	// The mix of both screens still deducts once.
	id, ap = file("2026-11-16", "2026-11-20")
	if code, b := hr(http.MethodPost, ap+"/approve", "{}"); code != http.StatusOK {
		t.Fatalf("step 1: %d %v", code, b)
	}
	if code, b := hr(http.MethodPost, leavePath+"/"+id.String()+"/approve", "{}"); code != http.StatusOK || status(id) != leaverequest.StatusApproved || taken() != "10" {
		t.Fatalf("leave page finishes the chain: %d %v %s", code, b, taken())
	}

	// Over balance: refused before anything is recorded.
	id, ap = file("2026-11-23", "2026-11-27")
	e.c.LeaveBalance.Update().Where(leavebalance.EmployeeID(jane.ID)).SetDaysRemaining(decimal.NewFromInt(1)).ExecX(ctx)
	for _, act := range []string{"approve", "escalate"} {
		code, b = hr(http.MethodPost, ap+"/"+act, "{}")
		if msg, _ := b["error"].(string); code != http.StatusBadRequest || !strings.HasPrefix(msg, "this request takes 5 days") {
			t.Fatalf("%s over balance: %d %v", act, code, b)
		}
	}
	if code, _ := hr(http.MethodPost, leavePath+"/"+id.String()+"/approve", "{}"); code != http.StatusBadRequest {
		t.Fatalf("leave page over balance: %d", code)
	}
	ar := e.c.ApprovalRequest.Query().Where(approvalrequest.ObjectID(id)).OnlyX(ctx)
	if ar.Status != approvalrequest.StatusPending || ar.CurrentSequence != 1 || status(id) != leaverequest.StatusPending {
		t.Fatalf("nothing may be recorded: %v %s", ar, status(id))
	}
	// Self approval is refused here too, and rejecting stays possible over balance.
	boss := e.staff(jane.ID, "approvals.decide")
	if code, _ := boss(http.MethodPost, ap+"/approve", "{}"); code != http.StatusForbidden {
		t.Fatalf("self approval: %d", code)
	}
	if code, b := hr(http.MethodPost, ap+"/reject", "{}"); code != http.StatusOK || status(id) != leaverequest.StatusRejected {
		t.Fatalf("reject over balance: %d %v", code, b)
	}
}

// TestLeaveSearchInheritedAndEntitlements: the request search, read-only platform types with the
// tenant's own settings, and deleting an entitlement.
func TestLeaveSearchInheritedAndEntitlements(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	hr := e.hr(e.tenant)
	annual := e.category("Annual Leave")
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "EMP-101")
	peter := hrmEmployee(ctx, e.c, e.tenant, "Peter", "Otieno", "EMP-202")
	for _, id := range []uuid.UUID{jane.ID, peter.ID} {
		if code, b := hr(http.MethodPost, leavePath, fileBody(id.String(), annual, "2026-11-02", "2026-11-03")); code != http.StatusCreated {
			t.Fatalf("file: %d %v", code, b)
		}
	}
	for q, want := range map[string]int{"jane": 1, "wanjiru%20JANE": 1, "202": 1, "e": 2, "nobody": 0, "%25": 0, "": 2} {
		code, b := hr(http.MethodGet, leavePath+"?from=2026-11-01&to=2026-11-30&search="+q, "")
		if total, _ := listTotal(t, b); code != http.StatusOK || total != want {
			t.Fatalf("search %q: want %d, got %d %v", q, want, code, b)
		}
	}
	if _, b := e.hr(uuid.New())(http.MethodGet, leavePath+"?from=2026-11-01&to=2026-11-30&search=jane", ""); b["total"] != float64(0) {
		t.Fatalf("search must stay in the tenant: %v", b)
	}

	// Entitlements.
	ent := e.c.LeaveEntitlement.Create().SetTenantID(e.tenant).SetEmployeeID(jane.ID).SetCategoryID(annual).SetYear(2026).SetDaysEntitled(decimal.NewFromInt(30)).SaveX(ctx)
	e.c.LeaveCategory.UpdateOneID(annual).SetDefaultAnnualDays(decimal.NewFromInt(21)).ExecX(ctx)
	e.balance(jane.ID, annual, 2026, 30, 4)
	del := "/hrm/leave/entitlements/" + ent.ID.String()
	if code, _ := e.hr(uuid.New())(http.MethodDelete, del, ""); code != http.StatusNotFound {
		t.Fatalf("another tenant's entitlement: %d", code)
	}
	if code, _ := e.staff(jane.ID, "hrm.leave.view")(http.MethodDelete, del, ""); code != http.StatusForbidden {
		t.Fatalf("staff must not delete entitlements: %d", code)
	}
	if code, _ := hr(http.MethodDelete, del, ""); code != http.StatusNoContent {
		t.Fatalf("delete entitlement: %d", code)
	}
	bal := e.c.LeaveBalance.Query().Where(leavebalance.EmployeeID(jane.ID)).OnlyX(ctx)
	if bal.DaysEntitled.String() != "21" || bal.DaysTaken.String() != "4" || bal.DaysRemaining.String() != "17" {
		t.Fatalf("balance after delete: %v", bal)
	}
	if code, _ := hr(http.MethodDelete, del, ""); code != http.StatusNotFound {
		t.Fatalf("second delete: %d", code)
	}

	// Platform types inherited by a tenant with none of its own.
	system := uuid.New()
	e.svc.WithSystemTenant(system)
	plat := e.c.LeaveCategory.Create().SetTenantID(system).SetName("Platform Annual").SaveX(ctx).ID
	e.tenant = uuid.New()
	hr = e.hr(e.tenant)
	code, list := hr(http.MethodGet, "/hrm/leave/categories", "")
	_, rows := listTotal(t, list)
	if code != http.StatusOK || len(rows) != 1 || rows[0].(map[string]any)["inherited"] != true || rows[0].(map[string]any)["balance_rule"] != "refuse" {
		t.Fatalf("inherited list: %d %v", code, list)
	}
	path := "/hrm/leave/categories/" + plat.String()
	if code, b := hr(http.MethodPut, path, `{"name":"Mine"}`); code == http.StatusOK || b["error"] != leave.ErrInheritedName.Error() {
		t.Fatalf("rename of a platform type: %d %v", code, b)
	}
	if code, b := hr(http.MethodDelete, path, ""); code == http.StatusOK || b["error"] != leave.ErrInheritedCategory.Error() {
		t.Fatalf("delete of a platform type: %d %v", code, b)
	}
	if code, b := hr(http.MethodPut, path+"/balance-rule", `{"balance_rule":"allow"}`); code != http.StatusOK || b["inherited"] != true {
		t.Fatalf("settings on a platform type: %d %v", code, b)
	}
	if c := e.c.LeaveCategory.GetX(ctx, plat); c.Name != "Platform Annual" || e.c.LeaveCategory.Query().CountX(ctx) != 2 {
		t.Fatalf("the platform row must not change or be copied: %v", c)
	}
	// Leave approved with no balance leaves a row with nothing entitled. For a platform type that
	// is still no balance, so the next request is not refused.
	if code, b := hr(http.MethodPut, path+"/balance-rule", `{"balance_rule":"refuse"}`); code != http.StatusOK {
		t.Fatalf("rule: %d %v", code, b)
	}
	amy := hrmEmployee(ctx, e.c, e.tenant, "Amy", "Njeri", "EMP-303")
	_, r := hr(http.MethodPost, leavePath, fileBody(amy.ID.String(), plat, "2026-11-02", "2026-11-03"))
	if code, b := hr(http.MethodPost, leavePath+"/"+r["id"].(string)+"/approve", "{}"); code != http.StatusOK {
		t.Fatalf("approve without a balance: %d %v", code, b)
	}
	if code, b := hr(http.MethodGet, previewPath(amy.ID, plat, "2026-11-09", "2026-11-10"), ""); code != http.StatusOK || b["refused"] != false || b["remaining_balance"] != nil {
		t.Fatalf("still no balance: %d %v", code, b)
	}
}
