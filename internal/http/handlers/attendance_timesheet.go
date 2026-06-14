package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

func (h *AttendanceHandler) registerTimesheetRoutes(ar chi.Router) {
	ar.Get("/timesheets", h.ListTimesheets)
	ar.Post("/timesheets", h.CreateTimesheet)
	ar.Put("/timesheets/{id}/entries", h.UpsertEntry)
	ar.Post("/timesheets/{id}/submit", h.SubmitTimesheet)
	ar.Post("/timesheets/{id}/approve", h.ApproveTimesheet)
	ar.Post("/timesheets/{id}/reject", h.RejectTimesheet)
}

func (h *AttendanceHandler) ListTimesheets(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListTimesheets(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list timesheets")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type timesheetBody struct {
	EmployeeID  string `json:"employee_id"`
	PeriodStart string `json:"period_start"`
	PeriodEnd   string `json:"period_end"`
	Notes       string `json:"notes"`
}

func (h *AttendanceHandler) CreateTimesheet(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b timesheetBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	start, err := parseDate(b.PeriodStart)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid period_start")
		return
	}
	end, err := parseDate(b.PeriodEnd)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid period_end")
		return
	}
	row, err := h.svc.CreateTimesheet(r.Context(), scope.TenantID, empID, start, end, b.Notes)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

type entryBody struct {
	ProjectID     string `json:"project_id"`
	Date          string `json:"date"`
	Task          string `json:"task_description"`
	RegularHours  string `json:"regular_hours"`
	OvertimeHours string `json:"overtime_hours"`
	BreakHours    string `json:"break_hours"`
}

func (h *AttendanceHandler) UpsertEntry(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	tsID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b entryBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	date, err := parseDate(b.Date)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid date")
		return
	}
	in := attendance.EntryInput{
		TimesheetID: tsID, Date: date, Task: b.Task,
		RegularHours: b.RegularHours, OvertimeHours: b.OvertimeHours, BreakHours: b.BreakHours,
	}
	if b.ProjectID != "" {
		if pid, perr := uuid.Parse(b.ProjectID); perr == nil {
			in.ProjectID = &pid
		}
	}
	row, err := h.svc.UpsertEntry(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "upsert_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *AttendanceHandler) SubmitTimesheet(w http.ResponseWriter, r *http.Request) {
	h.timesheetTransition(w, r, "submit")
}

func (h *AttendanceHandler) ApproveTimesheet(w http.ResponseWriter, r *http.Request) {
	h.timesheetTransition(w, r, "approve")
}

func (h *AttendanceHandler) RejectTimesheet(w http.ResponseWriter, r *http.Request) {
	h.timesheetTransition(w, r, "reject")
}

type timesheetActionBody struct {
	Reason string `json:"reason"`
}

func (h *AttendanceHandler) timesheetTransition(w http.ResponseWriter, r *http.Request, action string) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	ctx := r.Context()
	switch action {
	case "submit":
		row, terr := h.svc.SubmitTimesheet(ctx, scope.TenantID, id)
		writeTransition(w, row, terr)
	case "approve":
		uid := scope.UserID
		row, terr := h.svc.ApproveTimesheet(ctx, scope.TenantID, id, &uid)
		writeTransition(w, row, terr)
	case "reject":
		var b timesheetActionBody
		_ = json.NewDecoder(r.Body).Decode(&b)
		row, terr := h.svc.RejectTimesheet(ctx, scope.TenantID, id, b.Reason)
		writeTransition(w, row, terr)
	}
}

// writeTransition writes a 200 with the row or a 400 with the FSM error.
func writeTransition(w http.ResponseWriter, row any, err error) {
	if err != nil {
		writeError(w, http.StatusBadRequest, "transition_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}
