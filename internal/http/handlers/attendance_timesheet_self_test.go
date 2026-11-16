package handlers

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// selfRouter mounts the attendance routes behind fixed claims, with the employee resolver mapping
// the given auth user ids.
func selfRouter(t *testing.T, client *ent.Client, claims *authclient.Claims, employees map[string]uuid.UUID) http.Handler {
	t.Helper()
	prev := resolveSelfEmployee
	SetEmployeeResolver(func(_ context.Context, _ uuid.UUID, external string) (uuid.UUID, bool) {
		id, ok := employees[external]
		return id, ok
	})
	t.Cleanup(func() { resolveSelfEmployee = prev })
	var svc *attendance.Service
	if client != nil {
		svc = attendance.NewService(client)
	}
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			next.ServeHTTP(w, req.WithContext(authclient.ContextWithClaims(req.Context(), claims)))
		})
	})
	NewAttendanceHandler(zap.NewNop(), svc).RegisterRoutes(r)
	return r
}

func selfCall(h http.Handler, method, path, body string, tenant uuid.UUID) (int, map[string]any) {
	req := httptest.NewRequest(method, path, strings.NewReader(body))
	if tenant != uuid.Nil {
		req.Header.Set("X-Tenant-ID", tenant.String())
	}
	w := httptest.NewRecorder()
	h.ServeHTTP(w, req)
	var out map[string]any
	_ = json.Unmarshal(w.Body.Bytes(), &out)
	return w.Code, out
}

func serviceClaims() *authclient.Claims {
	return &authclient.Claims{IsService: true, ServiceName: "projects-api"}
}

func TestSelfTimesheetsCallerRules(t *testing.T) {
	tenant, user, emp := uuid.New(), uuid.New(), uuid.New()
	week := "/hrm/attendance/timesheets/for-user?from=2026-11-16&to=2026-11-22"

	// A signed-in user on a plan without attendance gets the standard feature lock.
	signed := &authclient.Claims{TenantID: tenant.String(), SubscriptionStatus: "ACTIVE", SubscriptionFeatures: []string{"hr_management"}}
	signed.Subject = user.String()
	code, body := selfCall(selfRouter(t, nil, signed, map[string]uuid.UUID{user.String(): emp}), http.MethodGet, week, "", uuid.Nil)
	if code != http.StatusForbidden || body["code"] != "feature_not_available" || body["required_feature"] != "attendance" {
		t.Fatalf("no attendance feature: %d %v", code, body)
	}

	// With the feature, a user may not act for someone else.
	signed.SubscriptionFeatures = []string{"attendance"}
	code, body = selfCall(selfRouter(t, nil, signed, map[string]uuid.UUID{user.String(): emp}), http.MethodGet,
		week+"&auth_user_id="+uuid.NewString(), "", uuid.Nil)
	if code != http.StatusForbidden || body["code"] != "forbidden" {
		t.Fatalf("another user's time: %d %v", code, body)
	}

	h := selfRouter(t, nil, serviceClaims(), map[string]uuid.UUID{user.String(): emp})
	// A service caller names the tenant and the user.
	if code, _ := selfCall(h, http.MethodGet, week+"&auth_user_id="+user.String(), "", uuid.Nil); code != http.StatusBadRequest {
		t.Fatalf("service call without X-Tenant-ID: %d, want 400", code)
	}
	if code, _ := selfCall(h, http.MethodGet, week+"&auth_user_id=nope", "", tenant); code != http.StatusBadRequest {
		t.Fatalf("service call with a bad auth_user_id: %d, want 400", code)
	}
	// A user without an employee record gets a named error, never an empty week.
	code, body = selfCall(h, http.MethodGet, week+"&auth_user_id="+uuid.NewString(), "", tenant)
	if code != http.StatusNotFound || body["code"] != "no_employee_record" || body["error"] == "" {
		t.Fatalf("no employee: %d %v", code, body)
	}
	for _, bad := range []string{
		`{"auth_user_id":"` + user.String() + `","date":"2026-11-17","period_start":"2026-11-16","period_end":"2026-11-22","regular_hours":"x"}`,
		`{"auth_user_id":"` + user.String() + `","date":"2026-11-17","period_start":"2026-11-16","period_end":"2026-11-22","regular_hours":"1","mode":"multiply"}`,
		`{"auth_user_id":"` + user.String() + `","date":"2026-11-17","period_start":"2026-11-16","period_end":"2026-11-22","regular_hours":"1","task_id":"` + uuid.NewString() + `"}`,
	} {
		if code, _ := selfCall(h, http.MethodPost, "/hrm/attendance/timesheets/for-user/entries", bad, tenant); code != http.StatusBadRequest {
			t.Errorf("%s: %d, want 400", bad, code)
		}
	}
}

// End to end against Postgres: the first entry opens the week, set and add, a second project on
// the same day, the week read, submit, and the lock afterwards.
func TestSelfTimesheetsFlow(t *testing.T) {
	client := handlersTestClient(t)
	tenant, user, emp := uuid.New(), uuid.New(), uuid.New()
	p1, p2, task := uuid.New(), uuid.New(), uuid.New()
	h := selfRouter(t, client, serviceClaims(), map[string]uuid.UUID{user.String(): emp})
	post := func(body string) (int, map[string]any) {
		return selfCall(h, http.MethodPost, "/hrm/attendance/timesheets/for-user/entries", body, tenant)
	}
	entry := func(project uuid.UUID, taskID, date, hours, mode string, billable bool) string {
		b, _ := json.Marshal(map[string]any{
			"auth_user_id": user.String(), "period_start": "2026-11-16", "period_end": "2026-11-22",
			"date": date, "project_id": project.String(), "task_id": taskID, "regular_hours": hours, "mode": mode, "billable": billable,
		})
		return string(b)
	}

	if code, body := post(entry(p1, task.String(), "2026-11-17", "2", "set", true)); code != http.StatusOK {
		t.Fatalf("first entry: %d %v", code, body)
	}
	code, body := post(entry(p1, task.String(), "2026-11-17", "1.25", "add", true))
	if code != http.StatusOK {
		t.Fatalf("timer add: %d %v", code, body)
	}
	if got := body["entry"].(map[string]any)["regular_hours"]; got != "3.25" {
		t.Fatalf("hours after add = %v, want 3.25", got)
	}
	if code, body := post(entry(p2, "", "2026-11-17", "4", "set", false)); code != http.StatusOK {
		t.Fatalf("second project the same day: %d %v", code, body)
	}
	if code, body := post(entry(p1, task.String(), "2026-11-17", "21", "add", true)); code != http.StatusBadRequest || body["code"] != "invalid_entry" {
		t.Fatalf("over 24 hours: %d %v", code, body)
	}

	code, body = selfCall(h, http.MethodGet, "/hrm/attendance/timesheets/for-user?from=2026-11-16&to=2026-11-22&auth_user_id="+user.String(), "", tenant)
	if code != http.StatusOK {
		t.Fatalf("week: %d %v", code, body)
	}
	if sheets := body["timesheets"].([]any); len(sheets) != 1 || sheets[0].(map[string]any)["status"] != "draft" {
		t.Fatalf("timesheets = %v", sheets)
	}
	var total decimal.Decimal
	billable := 0
	for _, e := range body["entries"].([]any) {
		m := e.(map[string]any)
		total = total.Add(decimal.RequireFromString(m["regular_hours"].(string)))
		if m["billable"] == true {
			billable++
		}
	}
	if !total.Equal(decimal.RequireFromString("7.25")) || billable != 1 {
		t.Fatalf("entries total %s, billable %d", total, billable)
	}

	submit := `{"auth_user_id":"` + user.String() + `","from":"2026-11-16","to":"2026-11-22"}`
	if code, body := selfCall(h, http.MethodPost, "/hrm/attendance/timesheets/for-user/submit", submit, tenant); code != http.StatusOK {
		t.Fatalf("submit: %d %v", code, body)
	}
	if code, body := selfCall(h, http.MethodPost, "/hrm/attendance/timesheets/for-user/submit", submit, tenant); code != http.StatusConflict || body["code"] != "nothing_to_submit" {
		t.Fatalf("second submit: %d %v", code, body)
	}
	if code, body := post(entry(p1, task.String(), "2026-11-18", "1", "set", true)); code != http.StatusConflict || body["code"] != "timesheet_locked" {
		t.Fatalf("entry on a submitted week: %d %v", code, body)
	}
	// Submitted hours reach the project-hours read projects-api uses for utilisation.
	rows, err := attendance.NewService(client).ProjectHours(context.Background(), tenant, []uuid.UUID{p1, p2}, time.Time{}, time.Time{})
	if err != nil {
		t.Fatal(err)
	}
	for _, r := range rows {
		want := map[uuid.UUID]string{p1: "3.25", p2: "4"}[r.ProjectID]
		if !r.SubmittedHours.Equal(decimal.RequireFromString(want)) {
			t.Errorf("project %s submitted hours %s, want %s", r.ProjectID, r.SubmittedHours, want)
		}
	}
}
