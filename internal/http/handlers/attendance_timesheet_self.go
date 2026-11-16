package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// featureAttendance is the plan feature behind attendance and timesheets.
const featureAttendance = "attendance"

// The for-user timesheet routes log time for one employee, found by their auth user id. projects-api
// calls them S2S (X-API-Key, X-Tenant-ID, auth_user_id of the signed-in user) for its timer and
// week grid; an employee may also call them with their own sign-in for themselves. A service key
// carries no plan features, so projects-api checks the tenant's attendance feature on the user's
// token before it calls; a signed-in caller is checked here.
func (h *AttendanceHandler) registerSelfTimesheetRoutes(ar chi.Router) {
	ar.Get("/timesheets/for-user", h.UserTimesheets)
	ar.Post("/timesheets/for-user/entries", h.LogUserEntry)
	ar.Post("/timesheets/for-user/submit", h.SubmitUserTimesheets)
}

// timesheetUser resolves the tenant and the employee a for-user call acts for, or writes the error.
// A service or platform-owner caller names the user (auth_user_id) and the tenant (X-Tenant-ID); a
// signed-in user acts for themselves only and needs the attendance feature.
func timesheetUser(w http.ResponseWriter, r *http.Request, authUserID string) (uuid.UUID, uuid.UUID, bool) {
	claims, ok := authclient.ClaimsFromContext(r.Context())
	if !ok || claims == nil {
		writeError(w, http.StatusUnauthorized, "unauthorized", "missing claims")
		return uuid.Nil, uuid.Nil, false
	}
	var tenantID uuid.UUID
	if claims.IsService || claims.IsPlatformOwner {
		if tenantID, ok = resolveTenant(w, r); !ok {
			return uuid.Nil, uuid.Nil, false
		}
		if _, err := uuid.Parse(authUserID); err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "auth_user_id must be a UUID")
			return uuid.Nil, uuid.Nil, false
		}
	} else {
		scope, ok := scopeFromRequest(w, r)
		if !ok {
			return uuid.Nil, uuid.Nil, false
		}
		if !claims.FeatureEnabled(featureAttendance) {
			authclient.WriteFeatureLocked(w, featureAttendance, "")
			return uuid.Nil, uuid.Nil, false
		}
		if authUserID != "" && !strings.EqualFold(authUserID, claims.Subject) {
			writeError(w, http.StatusForbidden, "forbidden", "you may log only your own time")
			return uuid.Nil, uuid.Nil, false
		}
		tenantID, authUserID = scope.TenantID, claims.Subject
	}
	if resolveSelfEmployee == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "employee lookup is not configured")
		return uuid.Nil, uuid.Nil, false
	}
	empID, found := resolveSelfEmployee(r.Context(), tenantID, strings.ToLower(authUserID))
	if !found {
		writeError(w, http.StatusNotFound, "no_employee_record",
			"This user has no employee record in ERP. Ask HR to add them as an employee before logging time.")
		return uuid.Nil, uuid.Nil, false
	}
	return tenantID, empID, true
}

// optionalUUID parses an optional id: nil for an empty string.
func optionalUUID(raw string) (*uuid.UUID, error) {
	if raw == "" {
		return nil, nil
	}
	id, err := uuid.Parse(raw)
	if err != nil {
		return nil, err
	}
	return &id, nil
}

// writeSelfTimesheetError maps the attendance errors of the for-user routes.
func writeSelfTimesheetError(w http.ResponseWriter, err error, fallback string) {
	switch {
	case errors.Is(err, attendance.ErrTimesheetLocked):
		writeError(w, http.StatusConflict, "timesheet_locked", err.Error())
	case errors.Is(err, attendance.ErrNothingToSubmit):
		writeError(w, http.StatusConflict, "nothing_to_submit", err.Error())
	case errors.Is(err, attendance.ErrInvalidEntry):
		writeError(w, http.StatusBadRequest, "invalid_entry", err.Error())
	default:
		writeError(w, http.StatusInternalServerError, "internal_error", fallback)
	}
}

// UserTimesheets godoc
// @Summary An employee's timesheets for a range
// @Description The timesheets of the employee linked to ?auth_user_id= that overlap ?from=..?to= (YYYY-MM-DD, inclusive), with their entries dated in the range. S2S (X-API-Key, X-Tenant-ID) or the employee's own sign-in. 404 no_employee_record when the user has no employee record.
// @Tags attendance
// @Produce json
// @Success 200 {object} attendance.EmployeeTimesheets
// @Router /hrm/attendance/timesheets/for-user [get]
func (h *AttendanceHandler) UserTimesheets(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	from, ferr := parseDate(q.Get("from"))
	to, terr := parseDate(q.Get("to"))
	if ferr != nil || terr != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "from and to must be YYYY-MM-DD")
		return
	}
	tenantID, empID, ok := timesheetUser(w, r, q.Get("auth_user_id"))
	if !ok {
		return
	}
	out, err := h.svc.EmployeeRange(r.Context(), tenantID, empID, from, to)
	if err != nil {
		writeSelfTimesheetError(w, err, "failed to load timesheets")
		return
	}
	writeJSON(w, http.StatusOK, out)
}

type userEntryBody struct {
	AuthUserID  string `json:"auth_user_id"`
	PeriodStart string `json:"period_start"`
	PeriodEnd   string `json:"period_end"`
	Date        string `json:"date"`
	ProjectID   string `json:"project_id"`
	TaskID      string `json:"task_id"`
	Billable    *bool  `json:"billable"`
	Task        string `json:"task_description"`
	Hours       string `json:"regular_hours"`
	// Mode is "set" (the default: the entry's hours become regular_hours) or "add" (a stopped
	// timer: regular_hours are added to the entry).
	Mode string `json:"mode"`
}

// LogUserEntry godoc
// @Summary Log an employee's time on a project
// @Description Sets (mode=set) or adds (mode=add) regular hours on the employee's entry for one date, project and task. The timesheet covering the date is used; without one, period_start..period_end is opened as a draft. 409 timesheet_locked when that timesheet is submitted or approved. POST so a lost response is never retried into a second add.
// @Tags attendance
// @Accept json
// @Produce json
// @Success 200 {object} attendance.LoggedEntry
// @Router /hrm/attendance/timesheets/for-user/entries [post]
func (h *AttendanceHandler) LogUserEntry(w http.ResponseWriter, r *http.Request) {
	var b userEntryBody
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 16<<10)).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in := attendance.EmployeeEntryInput{Billable: b.Billable, Task: strings.TrimSpace(b.Task)}
	var err error
	if in.Date, err = parseDate(b.Date); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid date")
		return
	}
	if in.PeriodStart, err = parseDate(b.PeriodStart); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid period_start")
		return
	}
	if in.PeriodEnd, err = parseDate(b.PeriodEnd); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid period_end")
		return
	}
	if in.Hours, err = decimal.NewFromString(b.Hours); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "regular_hours must be a decimal string")
		return
	}
	switch b.Mode {
	case "", "set":
	case "add":
		in.Add = true
	default:
		writeError(w, http.StatusBadRequest, "bad_request", "mode must be set or add")
		return
	}
	if in.ProjectID, err = optionalUUID(b.ProjectID); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "project_id must be a UUID")
		return
	}
	if in.TaskID, err = optionalUUID(b.TaskID); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "task_id must be a UUID")
		return
	}
	if in.TaskID != nil && in.ProjectID == nil {
		writeError(w, http.StatusBadRequest, "bad_request", "task_id needs a project_id")
		return
	}
	tenantID, empID, ok := timesheetUser(w, r, b.AuthUserID)
	if !ok {
		return
	}
	in.EmployeeID = empID
	out, err := h.svc.LogEmployeeEntry(r.Context(), tenantID, in)
	if err != nil {
		writeSelfTimesheetError(w, err, "failed to log time")
		return
	}
	writeJSON(w, http.StatusOK, out)
}

type userSubmitBody struct {
	AuthUserID string `json:"auth_user_id"`
	From       string `json:"from"`
	To         string `json:"to"`
}

// SubmitUserTimesheets godoc
// @Summary Submit an employee's timesheets for a range
// @Description Submits every draft or rejected timesheet of the employee that overlaps from..to. Approval stays in ERP. 409 nothing_to_submit when there is none.
// @Tags attendance
// @Accept json
// @Produce json
// @Success 200 {object} map[string]interface{}
// @Router /hrm/attendance/timesheets/for-user/submit [post]
func (h *AttendanceHandler) SubmitUserTimesheets(w http.ResponseWriter, r *http.Request) {
	var b userSubmitBody
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	from, ferr := parseDate(b.From)
	to, terr := parseDate(b.To)
	if ferr != nil || terr != nil || to.Before(from) {
		writeError(w, http.StatusBadRequest, "bad_request", "from and to must be YYYY-MM-DD, from first")
		return
	}
	tenantID, empID, ok := timesheetUser(w, r, b.AuthUserID)
	if !ok {
		return
	}
	rows, err := h.svc.SubmitEmployeeRange(r.Context(), tenantID, empID, from, to)
	if err != nil {
		writeSelfTimesheetError(w, err, "failed to submit timesheets")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}
