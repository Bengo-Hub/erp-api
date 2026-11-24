package handlers

import (
	"context"
	"fmt"
	"net/http"
	"sync"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/approvalrequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/staffshiftoverride"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshiftschedule"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
)

type leaveCall func(method, path, body string) (int, map[string]any)

// leaveEnv serves the leave and approvals routes as HR (every permission) or as a staff member.
type leaveEnv struct {
	c      *ent.Client
	tenant uuid.UUID
	users  map[string]uuid.UUID // auth user id to employee
	svc    *leave.Service
	appr   *approvals.Service
}

func newLeaveEnv(t *testing.T) *leaveEnv {
	t.Helper()
	c := handlersTestClient(t)
	e := &leaveEnv{c: c, tenant: uuid.New(), users: map[string]uuid.UUID{},
		svc: leave.NewService(c, nil), appr: approvals.NewService(c, nil)}
	e.svc.SetCalendar(attendance.NewService(c))
	e.svc.SetApprovals(e.appr)
	prev := resolveSelfEmployee
	SetEmployeeResolver(func(_ context.Context, _ uuid.UUID, ext string) (uuid.UUID, bool) {
		id, ok := e.users[ext]
		return id, ok
	})
	t.Cleanup(func() { resolveSelfEmployee = prev })
	return e
}

func (e *leaveEnv) as(claims *authclient.Claims) leaveCall {
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			next.ServeHTTP(w, req.WithContext(authclient.ContextWithClaims(req.Context(), claims)))
		})
	})
	NewLeaveHandler(zap.NewNop(), e.svc).RegisterRoutes(r)
	NewApprovalsHandler(zap.NewNop(), e.appr).RegisterRoutes(r)
	return func(method, path, body string) (int, map[string]any) {
		return selfCall(r, method, path, body, uuid.Nil)
	}
}

func (e *leaveEnv) hr(tenant uuid.UUID) leaveCall {
	cl := serviceClaims()
	cl.TenantID = tenant.String()
	return e.as(cl)
}

// staff signs in as a user linked to emp (uuid.Nil for a user with no employee record).
func (e *leaveEnv) staff(emp uuid.UUID, perms ...string) leaveCall {
	cl := &authclient.Claims{TenantID: e.tenant.String(), Permissions: perms}
	cl.Subject = uuid.NewString()
	if emp != uuid.Nil {
		e.users[cl.Subject] = emp
	}
	return e.as(cl)
}

func (e *leaveEnv) category(name string) uuid.UUID {
	return e.c.LeaveCategory.Create().SetTenantID(e.tenant).SetName(name).SaveX(context.Background()).ID
}

func ymd(s string) time.Time {
	d, err := time.Parse("2006-01-02", s)
	if err != nil {
		panic(err)
	}
	return d
}

func previewPath(emp, cat uuid.UUID, from, to string) string {
	return fmt.Sprintf("/hrm/leave/requests/preview?employee_id=%s&category_id=%s&start_date=%s&end_date=%s", emp, cat, from, to)
}

func fileBody(emp string, cat uuid.UUID, from, to string) string {
	return fmt.Sprintf(`{"employee_id":%q,"category_id":%q,"start_date":%q,"end_date":%q,"days_requested":"99"}`, emp, cat, from, to)
}

// TestLeaveDayCounting: the preview counts working or calendar days from the person's own plan.
// 2026-11-02 is a Monday.
func TestLeaveDayCounting(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	hr := e.hr(e.tenant)
	annual, maternity := e.category("Annual Leave"), e.category("Maternity Leave")
	want := func(emp, cat uuid.UUID, from, to, days string, skipped int) map[string]any {
		t.Helper()
		code, b := hr(http.MethodGet, previewPath(emp, cat, from, to), "")
		sk, _ := b["skipped"].([]any)
		if code != http.StatusOK || b["days"] != days || len(sk) != skipped {
			t.Fatalf("%s to %s: want %s days, %d skipped; got %d %v", from, to, days, skipped, code, b)
		}
		return b
	}

	// No shift and no company default: the tenant's default working days (Monday to Friday).
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "L-1")
	b := want(jane.ID, annual, "2026-11-02", "2026-11-08", "5", 2)
	if b["count_mode"] != "working_days" || b["remaining_balance"] != nil {
		t.Fatalf("preview: %v", b)
	}
	// The setting drives it, not a constant.
	if _, err := attendance.NewService(e.c).SaveSettings(ctx, e.tenant, []byte(`{"default_working_days":["Monday","Tuesday","Wednesday","Thursday","Friday","Saturday"]}`)); err != nil {
		t.Fatal(err)
	}
	want(jane.ID, annual, "2026-11-02", "2026-11-08", "6", 1)
	if _, err := attendance.NewService(e.c).SaveSettings(ctx, e.tenant, []byte(`{"default_working_days":["Monday","Tuesday","Wednesday","Thursday","Friday"]}`)); err != nil {
		t.Fatal(err)
	}
	// Maternity defaults to calendar days; HR can change it, and back.
	want(jane.ID, maternity, "2026-11-02", "2026-11-08", "7", 0)
	if code, b := hr(http.MethodPut, "/hrm/leave/categories/"+maternity.String()+"/count-mode", `{"count_mode":"working_days"}`); code != http.StatusOK || b["count_mode"] != "working_days" {
		t.Fatalf("set mode: %d %v", code, b)
	}
	want(jane.ID, maternity, "2026-11-02", "2026-11-08", "5", 2)
	if code, _ := hr(http.MethodPut, "/hrm/leave/categories/"+annual.String()+"/count-mode", `{"count_mode":"fortnights"}`); code != http.StatusBadRequest {
		t.Fatalf("bad mode must be 400, got %d", code)
	}
	if code, _ := e.hr(uuid.New())(http.MethodPut, "/hrm/leave/categories/"+annual.String()+"/count-mode", `{"count_mode":"calendar_days"}`); code != http.StatusNotFound {
		t.Fatalf("another tenant's leave type must be 404, got %d", code)
	}
	if code, _ := e.staff(jane.ID)(http.MethodPut, "/hrm/leave/categories/"+annual.String()+"/count-mode", `{"count_mode":"calendar_days"}`); code != http.StatusForbidden {
		t.Fatalf("staff must not change the count mode, got %d", code)
	}

	// National and county holidays: the county one only for staff of that region.
	e.c.PublicHoliday.Create().SetTenantID(e.tenant).SetName("Founders Day").SetDate(ymd("2026-11-03")).SaveX(ctx)
	e.c.PublicHoliday.Create().SetTenantID(e.tenant).SetName("Mombasa Day").SetDate(ymd("2026-11-04")).SetIsNational(false).SetCounty("mombasa").SaveX(ctx)
	e.c.PublicHoliday.Create().SetTenantID(uuid.New()).SetName("Other tenant").SetDate(ymd("2026-11-05")).SaveX(ctx)
	want(jane.ID, annual, "2026-11-02", "2026-11-08", "4", 3)
	coast := e.c.Region.Create().SetTenantID(e.tenant).SetName("Mombasa").SaveX(ctx)
	ali := hrmEmployee(ctx, e.c, e.tenant, "Ali", "Said", "L-2")
	e.c.HRDetails.Create().SetTenantID(e.tenant).SetEmployeeID(ali.ID).SetRegionID(coast.ID).SaveX(ctx)
	b = want(ali.ID, annual, "2026-11-02", "2026-11-08", "3", 4)
	first := b["skipped"].([]any)[0].(map[string]any)
	if first["date"] != "2026-11-03" || first["reason"] != "public_holiday" || first["name"] != "Founders Day" {
		t.Fatalf("skipped holiday: %v", first)
	}
	// Calendar days count holidays too.
	paternity := e.category("Paternity Leave")
	want(ali.ID, paternity, "2026-11-02", "2026-11-08", "7", 0)

	// A half-day override counts half and an off-duty override is skipped.
	for day, typ := range map[string]staffshiftoverride.OverrideType{"2026-11-09": staffshiftoverride.OverrideTypeHalfDay, "2026-11-10": staffshiftoverride.OverrideTypeOffDuty} {
		e.c.StaffShiftOverride.Create().SetTenantID(e.tenant).SetEmployeeID(jane.ID).SetDate(ymd(day)).SetOverrideType(typ).
			SetStartTime("08:00").SetEndTime("12:00").SaveX(ctx)
	}
	want(jane.ID, annual, "2026-11-09", "2026-11-13", "3.5", 2)

	// A night shift scheduled Saturday and Sunday: those are the working days.
	night := e.c.WorkShift.Create().SetTenantID(e.tenant).SetName("Night").SaveX(ctx)
	for _, d := range []workshiftschedule.Day{workshiftschedule.DaySaturday, workshiftschedule.DaySunday} {
		e.c.WorkShiftSchedule.Create().SetTenantID(e.tenant).SetWorkShiftID(night.ID).SetDay(d).SetStartTime("20:00").SetEndTime("05:00").SaveX(ctx)
	}
	otieno := e.c.Employee.UpdateOne(hrmEmployee(ctx, e.c, e.tenant, "Peter", "Otieno", "L-3")).SetWorkShiftID(night.ID).SaveX(ctx)
	want(otieno.ID, annual, "2026-11-09", "2026-11-15", "2", 5)

	// A rotating roster: two days on, two off from Monday 9 November, weekend included.
	ros := e.c.ShiftRoster.Create().SetTenantID(e.tenant).SetName("Rotation").SetCycleDays(4).SetStartDate(ymd("2026-11-09")).SaveX(ctx)
	mary := hrmEmployee(ctx, e.c, e.tenant, "Mary", "Akinyi", "L-4")
	e.c.ShiftAssignment.Create().SetTenantID(e.tenant).SetEmployeeID(mary.ID).SetRosterID(ros.ID).SetStartDate(ymd("2026-11-09")).SaveX(ctx)
	for i := 1; i <= 4; i++ {
		e.c.ShiftRosterSlot.Create().SetTenantID(e.tenant).SetRosterID(ros.ID).SetEmployeeID(mary.ID).SetCycleDay(i).
			SetIsOffDay(i > 2).SetStartTime("20:00").SetEndTime("05:00").SaveX(ctx)
	}
	want(mary.ID, annual, "2026-11-09", "2026-11-15", "4", 3) // 9, 10, 13 and 14

	// The company default shift applies when the person has none.
	e.c.WorkShift.Create().SetTenantID(e.tenant).SetName("Default").SetIsDefault(true).SetStartTime("08:00").SetEndTime("17:00").SaveX(ctx)
	def := hrmEmployee(ctx, e.c, e.tenant, "Def", "Shift", "L-5")
	want(def.ID, annual, "2026-11-09", "2026-11-15", "5", 2)

	// Balance of the start year, bad ranges, cross-tenant employee and type.
	e.c.LeaveBalance.Create().SetTenantID(e.tenant).SetEmployeeID(def.ID).SetCategoryID(annual).SetYear(2026).
		SetDaysEntitled(decimal.NewFromInt(21)).SetDaysTaken(decimal.NewFromInt(4)).SetDaysRemaining(decimal.NewFromInt(17)).SaveX(ctx)
	if b = want(def.ID, annual, "2026-11-09", "2026-11-15", "5", 2); b["remaining_balance"] != "17" || b["balance_year"] != float64(2026) {
		t.Fatalf("balance: %v", b)
	}
	for _, p := range []string{previewPath(def.ID, annual, "2026-11-15", "2026-11-09"), previewPath(def.ID, annual, "2026-01-01", "2028-01-01"), previewPath(def.ID, uuid.New(), "2026-11-09", "2026-11-10")} {
		if code, b := hr(http.MethodGet, p, ""); code != http.StatusBadRequest {
			t.Fatalf("%s must be 400, got %d %v", p, code, b)
		}
	}
	if code, _ := e.hr(uuid.New())(http.MethodGet, previewPath(def.ID, annual, "2026-11-09", "2026-11-10"), ""); code != http.StatusNotFound {
		t.Fatalf("another tenant's employee must be 404, got %d", code)
	}
}

// TestLeaveSelfService: staff file, list and cancel their own requests only; the server count
// wins; overlaps and empty ranges are refused; nobody approves their own request.
func TestLeaveSelfService(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	hr := e.hr(e.tenant)
	annual := e.category("Annual Leave")
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "L-1")
	peter := hrmEmployee(ctx, e.c, e.tenant, "Peter", "Otieno", "L-2")
	js, ps := e.staff(jane.ID), e.staff(peter.ID)
	const path = "/hrm/leave/requests"

	code, req := js(http.MethodPost, path, fileBody("", annual, "2026-11-02", "2026-11-08"))
	if code != http.StatusCreated || req["employee_id"] != jane.ID.String() || req["days_requested"] != "5" || req["status"] != "pending" {
		t.Fatalf("file own (client days ignored): %d %v", code, req)
	}
	id := req["id"].(string)
	if code, b := js(http.MethodPost, path, fileBody(jane.ID.String(), annual, "2026-11-16", "2026-11-16")); code != http.StatusCreated || b["days_requested"] != "1" {
		t.Fatalf("file with own id: %d %v", code, b)
	}
	// Someone else, without hrm.leave.manage.
	if code, _ := js(http.MethodPost, path, fileBody(peter.ID.String(), annual, "2026-11-02", "2026-11-03")); code != http.StatusForbidden {
		t.Fatalf("filing for someone else must be 403, got %d", code)
	}
	if code, _ := js(http.MethodGet, previewPath(peter.ID, annual, "2026-11-02", "2026-11-03"), ""); code != http.StatusForbidden {
		t.Fatalf("previewing for someone else must be 403, got %d", code)
	}
	if code, b := e.staff(uuid.Nil)(http.MethodPost, path, fileBody("", annual, "2026-11-02", "2026-11-03")); code != http.StatusForbidden || b["code"] != "not_an_employee" && b["error"] == nil {
		t.Fatalf("a user with no employee record must be 403, got %d %v", code, b)
	}
	if code, _ := e.hr(uuid.New())(http.MethodPost, path, fileBody(jane.ID.String(), annual, "2026-12-07", "2026-12-08")); code != http.StatusNotFound {
		t.Fatalf("another tenant's employee must be 404, got %d", code)
	}
	if n := e.c.LeaveRequest.Query().Where(leaverequest.EmployeeID(peter.ID)).CountX(ctx); n != 0 {
		t.Fatalf("refused requests must not be saved, got %d", n)
	}

	// Overlap (also by a boundary day) and a weekend with nothing to count.
	code, b := js(http.MethodPost, path, fileBody("", annual, "2026-11-08", "2026-11-10"))
	if code != http.StatusBadRequest || b["error"] != "these dates overlap pending leave from 2026-11-02 to 2026-11-08" {
		t.Fatalf("overlap: %d %v", code, b)
	}
	if code, b := js(http.MethodPost, path, fileBody("", annual, "2026-11-28", "2026-11-29")); code != http.StatusBadRequest || b["error"] != leave.ErrNoDays.Error() {
		t.Fatalf("zero days: %d %v", code, b)
	}
	if code, b := hr(http.MethodPost, path, fileBody(peter.ID.String(), annual, "2026-11-02", "2026-11-03")); code != http.StatusCreated || b["days_requested"] != "2" {
		t.Fatalf("HR files for anyone, and another person's dates do not overlap: %d %v", code, b)
	}

	// Two identical requests at once: exactly one wins.
	var wg sync.WaitGroup
	codes := make([]int, 2)
	for i := range codes {
		wg.Add(1)
		go func() {
			defer wg.Done()
			codes[i], _ = ps(http.MethodPost, path, fileBody("", annual, "2026-12-07", "2026-12-11"))
		}()
	}
	wg.Wait()
	if codes[0]+codes[1] != http.StatusCreated+http.StatusBadRequest {
		t.Fatalf("concurrent overlap: %v", codes)
	}

	// Own list and leave types need no permission; everyone's list does.
	_, list := js(http.MethodGet, path+"?mine=true&employee_id="+peter.ID.String()+"&from=2026-11-01&to=2026-12-31", "")
	if total, _ := listTotal(t, list); total != 2 {
		t.Fatalf("own list: %v", list)
	}
	if code, _ := js(http.MethodGet, path, ""); code != http.StatusForbidden {
		t.Fatalf("full list without view must be 403, got %d", code)
	}
	code, list = js(http.MethodGet, "/hrm/leave/categories", "")
	if _, rows := listTotal(t, list); code != http.StatusOK || len(rows) != 1 || rows[0].(map[string]any)["count_mode"] != "working_days" {
		t.Fatalf("leave types for staff: %d %v", code, list)
	}

	// Cancel: not someone else's, own while pending, not once approved.
	if code, _ := ps(http.MethodPost, path+"/"+id+"/cancel", "{}"); code != http.StatusNotFound {
		t.Fatalf("cancelling someone else's request must be 404, got %d", code)
	}
	if code, b := js(http.MethodPost, path+"/"+id+"/cancel", "{}"); code != http.StatusOK || b["status"] != "cancelled" {
		t.Fatalf("cancel own: %d %v", code, b)
	}
	code, req = js(http.MethodPost, path, fileBody("", annual, "2026-11-02", "2026-11-06"))
	if code != http.StatusCreated {
		t.Fatalf("cancelled dates are free again: %d %v", code, req)
	}
	id = req["id"].(string)

	// Nobody approves their own request, even with the permission.
	e.users["jane-boss"] = jane.ID
	boss := &authclient.Claims{TenantID: e.tenant.String(), Permissions: []string{"hrm.leave.approve", "approvals.decide"}}
	boss.Subject = "jane-boss"
	if code, _ := e.as(boss)(http.MethodPost, path+"/"+id+"/approve", "{}"); code != http.StatusForbidden {
		t.Fatalf("self approval must be 403, got %d", code)
	}
	ar := e.c.ApprovalRequest.Create().SetTenantID(e.tenant).SetModule(approvalrequest.ModuleLeaveRequest).
		SetObjectID(uuid.New()).SetRequesterEmployeeID(jane.ID).SaveX(ctx)
	for _, act := range []string{"approve", "escalate"} {
		if code, b := e.as(boss)(http.MethodPost, "/approvals/requests/"+ar.ID.String()+"/"+act, "{}"); code != http.StatusForbidden {
			t.Fatalf("self %s through approvals must be 403, got %d %v", act, code, b)
		}
	}
	if code, b := hr(http.MethodPost, path+"/"+id+"/approve", "{}"); code != http.StatusOK || b["status"] != "approved" {
		t.Fatalf("approve: %d %v", code, b)
	}
	if code, _ := js(http.MethodPost, path+"/"+id+"/cancel", "{}"); code != http.StatusBadRequest {
		t.Fatalf("staff cancelling approved leave must be refused, got %d", code)
	}
	if st := e.c.LeaveRequest.GetX(ctx, uuid.MustParse(id)).Status; st != leaverequest.StatusApproved {
		t.Fatalf("approved leave must stay approved, got %s", st)
	}
	if code, b := js(http.MethodPost, path, fileBody("", annual, "2026-11-06", "2026-11-09")); code != http.StatusBadRequest {
		t.Fatalf("overlap with approved leave: %d %v", code, b)
	}
}

// TestLeaveInheritedTypes: a tenant using the platform leave types files against them and sets a
// count mode without copying or changing the platform row.
func TestLeaveInheritedTypes(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	system := uuid.New()
	e.svc.WithSystemTenant(system)
	cat := e.c.LeaveCategory.Create().SetTenantID(system).SetName("Maternity Leave").SaveX(ctx).ID
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "L-1")
	if code, b := e.hr(e.tenant)(http.MethodPut, "/hrm/leave/categories/"+cat.String()+"/count-mode", `{"count_mode":"working_days"}`); code != http.StatusOK {
		t.Fatalf("inherited type: %d %v", code, b)
	}
	if code, b := e.staff(jane.ID)(http.MethodPost, "/hrm/leave/requests", fileBody("", cat, "2026-11-02", "2026-11-08")); code != http.StatusCreated || b["days_requested"] != "5" {
		t.Fatalf("file: %d %v", code, b)
	}
	other := hrmEmployee(ctx, e.c, system, "Other", "Tenant", "L-9")
	if code, b := e.hr(system)(http.MethodGet, previewPath(other.ID, cat, "2026-11-02", "2026-11-08"), ""); code != http.StatusOK || b["days"] != "7" {
		t.Fatalf("the platform default must not change for others: %d %v", code, b)
	}
	if n := e.c.LeaveCategory.Query().CountX(ctx); n != 1 {
		t.Fatalf("platform type was copied: %d rows", n)
	}
}

// TestLeaveCancelClosesApproval: cancelling a request that sits in an approval workflow takes it
// out of the approvers' queue.
func TestLeaveCancelClosesApproval(t *testing.T) {
	e := newLeaveEnv(t)
	ctx := context.Background()
	annual := e.category("Annual Leave")
	jane := hrmEmployee(ctx, e.c, e.tenant, "Jane", "Wanjiru", "L-1")
	js := e.staff(jane.ID)
	_, req := js(http.MethodPost, "/hrm/leave/requests", fileBody("", annual, "2026-11-02", "2026-11-06"))
	id := req["id"].(string)
	ar := e.c.ApprovalRequest.Create().SetTenantID(e.tenant).SetModule(approvalrequest.ModuleLeaveRequest).
		SetObjectID(uuid.MustParse(id)).SetRequesterEmployeeID(jane.ID).SaveX(ctx)
	if code, b := js(http.MethodPost, "/hrm/leave/requests/"+id+"/cancel", "{}"); code != http.StatusOK {
		t.Fatalf("cancel: %d %v", code, b)
	}
	if st := e.c.ApprovalRequest.GetX(ctx, ar.ID).Status; st != approvalrequest.StatusCancelled {
		t.Fatalf("approval request must be cancelled, got %s", st)
	}
}
