package handlers

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

func (h *AttendanceHandler) registerRosterRoutes(ar chi.Router) {
	ar.Get("/rosters", h.ListRosters)
	ar.Post("/rosters", h.CreateRoster)
	ar.Delete("/rosters/{id}", h.DeleteRoster)
	ar.Get("/rosters/{id}/slots", h.ListSlots)
	ar.Put("/rosters/{id}/slots", h.UpsertSlot)
	ar.Get("/assignments", h.ListAssignments)
	ar.Post("/assignments", h.AssignRoster)
	ar.Delete("/assignments/{id}", h.DeleteAssignment)
	ar.Get("/overrides", h.ListOverrides)
	ar.Post("/overrides", h.CreateOverride)
	ar.Put("/overrides/{id}", h.UpdateOverride)
	ar.Patch("/overrides/{id}", h.UpdateOverride)
	ar.Delete("/overrides/{id}", h.DeleteOverride)

	// Weekly shift planner (drawable per-cell roster).
	ar.Get("/shift-planner", h.ResolvePlanner)
	ar.Put("/shift-planner/cell", h.UpsertPlannerCell)
	ar.Delete("/shift-planner/cell", h.ClearPlannerCell)
}

// ---- Shift planner (per-cell) ----

func (h *AttendanceHandler) ResolvePlanner(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	from, err := parseDate(r.URL.Query().Get("from"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid or missing 'from'")
		return
	}
	to, err := parseDate(r.URL.Query().Get("to"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid or missing 'to'")
		return
	}
	rows, err := h.svc.ResolvePlanner(r.Context(), scope.TenantID, from, to)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to resolve planner")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}

type plannerCellBody struct {
	EmployeeID  string `json:"employee_id"`
	Date        string `json:"date"`
	WorkShiftID string `json:"work_shift_id"`
	StartTime   string `json:"start_time"`
	EndTime     string `json:"end_time"`
}

func (h *AttendanceHandler) UpsertPlannerCell(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b plannerCellBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	date, err := parseDate(b.Date)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid date")
		return
	}
	in := attendance.PlannerCellInput{
		EmployeeID: empID, Date: date,
		StartTime: b.StartTime, EndTime: b.EndTime,
	}
	if b.WorkShiftID != "" {
		sid, perr := uuid.Parse(b.WorkShiftID)
		if perr != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "invalid work_shift_id")
			return
		}
		in.WorkShiftID = &sid
	}
	uid := scope.UserID
	in.CreatedBy = &uid
	row, err := h.svc.UpsertPlannerCell(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "upsert_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *AttendanceHandler) ClearPlannerCell(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	empID, err := uuid.Parse(r.URL.Query().Get("employee_id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	date, err := parseDate(r.URL.Query().Get("date"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid date")
		return
	}
	if err := h.svc.ClearPlannerCell(r.Context(), scope.TenantID, empID, date); err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Rosters ----

func (h *AttendanceHandler) ListRosters(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	rows, err := h.svc.ListRosters(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list rosters")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type rosterBody struct {
	Name      string `json:"name"`
	CycleDays int    `json:"cycle_days"`
	StartDate string `json:"start_date"`
}

func (h *AttendanceHandler) CreateRoster(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b rosterBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	start, err := parseDate(b.StartDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid start_date")
		return
	}
	row, err := h.svc.CreateRoster(r.Context(), scope.TenantID, b.Name, b.CycleDays, start)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", clientMessage(err))
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *AttendanceHandler) DeleteRoster(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteRoster(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *AttendanceHandler) ListSlots(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	rows, err := h.svc.ListSlots(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list slots")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type slotBody struct {
	EmployeeID string `json:"employee_id"`
	CycleDay   int    `json:"cycle_day"`
	StartTime  string `json:"start_time"`
	EndTime    string `json:"end_time"`
	IsOffDay   bool   `json:"is_off_day"`
}

func (h *AttendanceHandler) UpsertSlot(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	rosterID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b slotBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	row, err := h.svc.UpsertSlot(r.Context(), scope.TenantID, attendance.SlotInput{
		RosterID: rosterID, EmployeeID: empID, CycleDay: b.CycleDay,
		StartTime: b.StartTime, EndTime: b.EndTime, IsOffDay: b.IsOffDay,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "upsert_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// ---- Assignments ----

func (h *AttendanceHandler) ListAssignments(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListAssignments(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list assignments")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type assignBody struct {
	EmployeeID string `json:"employee_id"`
	RosterID   string `json:"roster_id"`
	StartDate  string `json:"start_date"`
	EndDate    string `json:"end_date"`
}

func (h *AttendanceHandler) AssignRoster(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b assignBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	rosterID, err := uuid.Parse(b.RosterID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid roster_id")
		return
	}
	start, err := parseDate(b.StartDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid start_date")
		return
	}
	var end *time.Time
	if d, derr := parseDate(b.EndDate); derr == nil {
		end = &d
	}
	row, err := h.svc.AssignRoster(r.Context(), scope.TenantID, empID, rosterID, start, end)
	if err != nil {
		writeError(w, http.StatusBadRequest, "assign_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *AttendanceHandler) DeleteAssignment(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteAssignment(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Overrides ----

func (h *AttendanceHandler) ListOverrides(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListOverrides(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list overrides")
		return
	}
	p := pagination.Parse(r)
	page, total := pageWindow(rows, p)
	writePaginated(w, h.svc.OverrideViews(r.Context(), scope.TenantID, page), total, p)
}

type overrideBody struct {
	EmployeeID   string `json:"employee_id"`
	Date         string `json:"date"`
	OverrideType string `json:"override_type"`
	StartTime    string `json:"start_time"`
	EndTime      string `json:"end_time"`
	Reason       string `json:"reason"`
	Status       string `json:"status"`
}

// decodeOverride reads an override body, writing the 400 itself on failure.
func decodeOverride(w http.ResponseWriter, r *http.Request) (attendance.OverrideInput, bool) {
	var b overrideBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return attendance.OverrideInput{}, false
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return attendance.OverrideInput{}, false
	}
	date, err := parseDate(b.Date)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid date")
		return attendance.OverrideInput{}, false
	}
	return attendance.OverrideInput{
		EmployeeID: empID, Date: date, OverrideType: b.OverrideType,
		StartTime: b.StartTime, EndTime: b.EndTime, Reason: b.Reason, Status: b.Status,
	}, true
}

func (h *AttendanceHandler) CreateOverride(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	in, ok := decodeOverride(w, r)
	if !ok {
		return
	}
	uid := scope.UserID
	in.CreatedBy = &uid
	row, err := h.svc.CreateOverride(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", clientMessage(err))
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

// UpdateOverride edits one of the tenant's shift overrides, planner rows included (PUT and
// PATCH take the full body).
func (h *AttendanceHandler) UpdateOverride(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := decodeOverride(w, r)
	if !ok {
		return
	}
	row, err := h.svc.UpdateOverride(r.Context(), scope.TenantID, id, in)
	if err != nil {
		writeUpdateError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// DeleteOverride removes one of the tenant's shift overrides; for a planner row this clears
// the planner cell.
func (h *AttendanceHandler) DeleteOverride(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteOverride(r.Context(), scope.TenantID, id); err != nil {
		writeUpdateError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
