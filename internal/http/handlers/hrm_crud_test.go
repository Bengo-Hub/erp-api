package handlers

import (
	"context"
	"fmt"
	"net/http"
	"testing"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	authclient "github.com/Bengo-Hub/shared-auth-client"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/contactdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/modules/appraisals"
	"github.com/Bengo-Hub/erp-api/internal/modules/recruitment"
	"github.com/Bengo-Hub/erp-api/internal/modules/training"
)

// hrmRouter mounts route groups behind service claims for one tenant (every permission
// granted). scopeFromRequest reads the tenant from the claims, never from a header.
func hrmRouter(tenant uuid.UUID, register ...func(chi.Router)) http.Handler {
	claims := serviceClaims()
	claims.TenantID = tenant.String()
	r := chi.NewRouter()
	r.Use(func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, req *http.Request) {
			next.ServeHTTP(w, req.WithContext(authclient.ContextWithClaims(req.Context(), claims)))
		})
	})
	for _, fn := range register {
		fn(r)
	}
	return r
}

// listTotal reads the total of a paginated list response.
func listTotal(t *testing.T, body map[string]any) (int, []any) {
	t.Helper()
	total, _ := body["total"].(float64)
	data, _ := body["data"].([]any)
	return int(total), data
}

func hrmEmployee(ctx context.Context, c *ent.Client, tenant uuid.UUID, first, last, number string) *ent.Employee {
	return c.Employee.Create().SetTenantID(tenant).SetFirstName(first).SetLastName(last).
		SetEmployeeNumber(number).SaveX(ctx)
}

// TestAppraisalCycleGoalEditsAndSearch: cycle edit and delete (refused while it holds
// appraisals), appraisal search by employee name or number, goal edit and delete.
func TestAppraisalCycleGoalEditsAndSearch(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	h := hrmRouter(tenant, NewAppraisalsHandler(zap.NewNop(), appraisals.NewService(client)).RegisterRoutes)
	call := func(method, path, body string) (int, map[string]any) { return selfCall(h, method, path, body, tenant) }

	jane := hrmEmployee(ctx, client, tenant, "Jane", "Wanjiru", "S-1001")
	peter := hrmEmployee(ctx, client, tenant, "Peter", "Otieno", "S-1002")

	code, cyc := call(http.MethodPost, "/hrm/appraisals/cycles", `{"name":"2026 H1","start_date":"2026-01-01","end_date":"2026-06-30"}`)
	if code != http.StatusCreated {
		t.Fatalf("create cycle: %d %v", code, cyc)
	}
	cycleID := cyc["id"].(string)
	if code, body := call(http.MethodPut, "/hrm/appraisals/cycles/"+cycleID, `{"name":"2026 first half","start_date":"2026-01-01T00:00:00Z","end_date":"2026-06-30"}`); code != http.StatusOK || body["name"] != "2026 first half" {
		t.Fatalf("update cycle: %d %v", code, body)
	}
	if code, _ := call(http.MethodPut, "/hrm/appraisals/cycles/"+cycleID, `{"name":"x","start_date":"2026-06-01","end_date":"2026-01-01"}`); code != http.StatusBadRequest {
		t.Fatalf("end before start must be refused, got %d", code)
	}

	for _, e := range []*ent.Employee{jane, peter} {
		if code, body := call(http.MethodPost, "/hrm/appraisals/", fmt.Sprintf(`{"cycle_id":%q,"employee_id":%q}`, cycleID, e.ID)); code != http.StatusCreated {
			t.Fatalf("create appraisal: %d %v", code, body)
		}
	}
	if code, body := call(http.MethodDelete, "/hrm/appraisals/cycles/"+cycleID, ""); code != http.StatusConflict || body["code"] != "in_use" {
		t.Fatalf("delete used cycle: %d %v", code, body)
	}

	for term, want := range map[string]int{"wanj": 1, "jane%20wanjiru": 1, "S-100": 2, "jane%20otieno": 0, "": 2} {
		code, body := call(http.MethodGet, "/hrm/appraisals/?search="+term, "")
		if total, _ := listTotal(t, body); code != http.StatusOK || total != want {
			t.Fatalf("search %q: %d total %d, want %d", term, code, total, want)
		}
	}

	_, empty := call(http.MethodPost, "/hrm/appraisals/cycles", `{"name":"Unused","start_date":"2026-07-01","end_date":"2026-12-31"}`)
	if code, _ := call(http.MethodDelete, "/hrm/appraisals/cycles/"+empty["id"].(string), ""); code != http.StatusNoContent {
		t.Fatalf("delete empty cycle: %d", code)
	}
	if code, _ := call(http.MethodDelete, "/hrm/appraisals/cycles/"+empty["id"].(string), ""); code != http.StatusNotFound {
		t.Fatalf("delete twice: %d", code)
	}
	other := hrmRouter(uuid.New(), NewAppraisalsHandler(zap.NewNop(), appraisals.NewService(client)).RegisterRoutes)
	if code, _ := selfCall(other, http.MethodDelete, "/hrm/appraisals/cycles/"+cycleID, "", uuid.Nil); code != http.StatusNotFound {
		t.Fatalf("another tenant must not see the cycle, got %d", code)
	}

	code, g := call(http.MethodPost, "/hrm/appraisals/goals", fmt.Sprintf(`{"employee_id":%q,"title":"Ship v2","category":"Delivery","weight":1}`, jane.ID))
	if code != http.StatusCreated {
		t.Fatalf("create goal: %d %v", code, g)
	}
	goalID := g["id"].(string)
	code, g = call(http.MethodPut, "/hrm/appraisals/goals/"+goalID, fmt.Sprintf(`{"employee_id":%q,"title":"Ship v2.1","category":"Quality","weight":2,"end_date":"2026-09-30"}`, peter.ID))
	if code != http.StatusOK || g["title"] != "Ship v2.1" || g["employee_name"] != "Peter Otieno" || g["category"] != "Quality" || g["weight"] != "2" {
		t.Fatalf("update goal: %d %v", code, g)
	}
	if code, _ := call(http.MethodPut, "/hrm/appraisals/goals/"+goalID, `{"title":"No owner"}`); code != http.StatusBadRequest {
		t.Fatalf("an employee goal without an employee must be refused, got %d", code)
	}
	if code, _ := call(http.MethodPost, "/hrm/appraisals/goals/"+goalID+"/progress", `{"progress":40}`); code != http.StatusCreated {
		t.Fatalf("progress: %d", code)
	}
	if code, _ := call(http.MethodDelete, "/hrm/appraisals/goals/"+goalID, ""); code != http.StatusNoContent {
		t.Fatalf("delete goal: %d", code)
	}
	if n := client.GoalProgress.Query().CountX(ctx); n != 0 {
		t.Fatalf("progress rows left after goal delete: %d", n)
	}
}

// TestTrainingEnrollmentEvaluationEdits: moving an enrolment checks capacity, an evaluated
// enrolment can neither move nor be deleted, evaluations edit and delete.
func TestTrainingEnrollmentEvaluationEdits(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	h := hrmRouter(tenant, NewTrainingHandler(zap.NewNop(), training.NewService(client)).RegisterRoutes)
	call := func(method, path, body string) (int, map[string]any) { return selfCall(h, method, path, body, tenant) }

	course := func(title string, capacity int) *ent.TrainingCourse {
		return client.TrainingCourse.Create().SetTenantID(tenant).SetTitle(title).SetCapacity(capacity).
			SetStartDate(time.Now()).SetEndDate(time.Now().AddDate(0, 1, 0)).SaveX(ctx)
	}
	full, open := course("Excel", 1), course("Safety", 0)
	e1 := hrmEmployee(ctx, client, tenant, "Ann", "Kamau", "T-1")
	e2 := hrmEmployee(ctx, client, tenant, "Ben", "Mutua", "T-2")

	enrol := func(c *ent.TrainingCourse, e *ent.Employee) string {
		code, body := call(http.MethodPost, "/hrm/training/enrollments", fmt.Sprintf(`{"course_id":%q,"employee_id":%q}`, c.ID, e.ID))
		if code != http.StatusCreated {
			t.Fatalf("enrol: %d %v", code, body)
		}
		return body["id"].(string)
	}
	enrol(full, e2)
	id := enrol(open, e1)

	if code, _ := call(http.MethodPut, "/hrm/training/enrollments/"+id, fmt.Sprintf(`{"course_id":%q,"employee_id":%q}`, full.ID, e1.ID)); code != http.StatusBadRequest {
		t.Fatalf("a full course must refuse the move, got %d", code)
	}
	if code, body := call(http.MethodPut, "/hrm/training/enrollments/"+id, fmt.Sprintf(`{"course_id":%q,"employee_id":%q}`, open.ID, e1.ID)); code != http.StatusOK || body["course_name"] != "Safety" {
		t.Fatalf("unchanged update: %d %v", code, body)
	}

	code, ev := call(http.MethodPost, "/hrm/training/evaluations", fmt.Sprintf(`{"course_id":%q,"employee_id":%q,"rating":4,"feedback":"good"}`, open.ID, e1.ID))
	if code != http.StatusCreated {
		t.Fatalf("evaluate: %d %v", code, ev)
	}
	evID := ev["id"].(string)
	if code, body := call(http.MethodPut, "/hrm/training/enrollments/"+id, fmt.Sprintf(`{"course_id":%q,"employee_id":%q}`, open.ID, e2.ID)); code != http.StatusConflict || body["code"] != "in_use" {
		t.Fatalf("moving an evaluated enrolment: %d %v", code, body)
	}
	if code, _ := call(http.MethodDelete, "/hrm/training/enrollments/"+id, ""); code != http.StatusConflict {
		t.Fatalf("deleting an evaluated enrolment: %d", code)
	}

	if code, body := call(http.MethodPut, "/hrm/training/evaluations/"+evID, `{"rating":9,"feedback":"great"}`); code != http.StatusOK || body["rating"] != float64(5) || body["feedback"] != "great" || body["employee_name"] != "Ann Kamau" {
		t.Fatalf("update evaluation: %d %v", code, body)
	}
	if code, _ := call(http.MethodDelete, "/hrm/training/evaluations/"+evID, ""); code != http.StatusNoContent {
		t.Fatalf("delete evaluation: %d", code)
	}
	if code, _ := call(http.MethodDelete, "/hrm/training/enrollments/"+id, ""); code != http.StatusNoContent {
		t.Fatalf("delete enrolment: %d", code)
	}
	if code, _ := call(http.MethodDelete, "/hrm/training/evaluations/"+evID, ""); code != http.StatusNotFound {
		t.Fatalf("delete missing evaluation: %d", code)
	}

	// A course with enrolments cannot be deleted; one without can, once.
	if code, body := call(http.MethodDelete, "/hrm/training/courses/"+full.ID.String(), ""); code != http.StatusConflict || body["code"] != "in_use" {
		t.Fatalf("deleting a course with enrolments: %d %v", code, body)
	}
	if code, _ := call(http.MethodDelete, "/hrm/training/courses/"+open.ID.String(), ""); code != http.StatusNoContent {
		t.Fatalf("delete course without enrolments: %d", code)
	}
	if code, _ := call(http.MethodDelete, "/hrm/training/courses/"+open.ID.String(), ""); code != http.StatusNotFound {
		t.Fatalf("delete missing course: %d", code)
	}
}

// TestCandidateDeleteAndHireCopiesDetails: a candidate with applications cannot be deleted;
// hiring copies the phone, the matching department and job title and the offered start date.
func TestCandidateDeleteAndHireCopiesDetails(t *testing.T) {
	client := handlersTestClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	h := hrmRouter(tenant, NewRecruitmentHandler(zap.NewNop(), recruitment.NewService(client), nil).RegisterRoutes)
	call := func(method, path, body string) (int, map[string]any) { return selfCall(h, method, path, body, tenant) }

	dept := client.Department.Create().SetTenantID(tenant).SetTitle("Sales").SaveX(ctx)
	title := client.JobTitle.Create().SetTenantID(tenant).SetTitle("Sales Executive").SaveX(ctx)
	posting := client.JobPosting.Create().SetTenantID(tenant).SetTitle("sales executive").
		SetDepartment("SALES").SetStatus("open").SaveX(ctx)

	_, lone := call(http.MethodPost, "/hrm/recruitment/candidates", `{"full_name":"Tom Were","email":"tom@example.com"}`)
	if code, _ := call(http.MethodDelete, "/hrm/recruitment/candidates/"+lone["id"].(string), ""); code != http.StatusNoContent {
		t.Fatalf("delete candidate: %d", code)
	}

	_, cand := call(http.MethodPost, "/hrm/recruitment/candidates", `{"full_name":"Mary Achieng","email":"mary@example.com","phone":"+254700000001"}`)
	candID := cand["id"].(string)
	code, app := call(http.MethodPost, "/hrm/recruitment/applications", fmt.Sprintf(`{"job_id":%q,"candidate_id":%q}`, posting.ID, candID))
	if code != http.StatusCreated {
		t.Fatalf("apply: %d %v", code, app)
	}
	if code, body := call(http.MethodDelete, "/hrm/recruitment/candidates/"+candID, ""); code != http.StatusConflict || body["code"] != "in_use" {
		t.Fatalf("delete candidate with application: %d %v", code, body)
	}

	appID := app["id"].(string)
	var res map[string]any
	for _, step := range []string{
		`{"status":"screening"}`, `{"status":"interview"}`,
		`{"status":"offered","offer_details":"KES 80,000 a month. Start date: 2026-12-01"}`,
		`{"status":"hired","create_employee":true}`,
	} {
		if code, res = call(http.MethodPost, "/hrm/recruitment/applications/"+appID+"/transition", step); code != http.StatusOK {
			t.Fatalf("transition %s: %d %v", step, code, res)
		}
	}
	empID := uuid.MustParse(res["employee_id"].(string))
	emp := client.Employee.GetX(ctx, empID)
	if emp.FirstName != "Mary" || emp.LastName != "Achieng" || emp.Email != "mary@example.com" {
		t.Fatalf("employee identity: %+v", emp)
	}
	hr := client.HRDetails.Query().Where(hrdetails.EmployeeID(empID)).OnlyX(ctx)
	if hr.DepartmentID == nil || *hr.DepartmentID != dept.ID || hr.JobTitleID == nil || *hr.JobTitleID != title.ID {
		t.Fatalf("department/job title not matched: %+v", hr)
	}
	if hr.DateJoined == nil || hr.DateJoined.Format("2006-01-02") != "2026-12-01" {
		t.Fatalf("start date not copied: %v", hr.DateJoined)
	}
	contact := client.ContactDetails.Query().Where(contactdetails.EmployeeID(empID)).OnlyX(ctx)
	if contact.Phone == nil || *contact.Phone != "+254700000001" {
		t.Fatalf("phone not copied: %v", contact.Phone)
	}
}
