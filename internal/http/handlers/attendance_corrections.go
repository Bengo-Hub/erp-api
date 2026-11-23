package handlers

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// registerCorrectionRoutes mounts regularisations and overtime requests. HR files for anyone
// (employee_id in the body, hrm.attendance.manage); staff file for themselves through ESS.
// Decisions go through /approvals (modules attendance_regularisation and overtime_request).
func (h *AttendanceHandler) registerCorrectionRoutes(ar chi.Router) {
	ar.Get("/regularisations", h.ListRegularisations)
	ar.Post("/regularisations", h.CreateRegularisation)
	ar.Get("/overtime-requests", h.ListOvertimeRequests)
	ar.Post("/overtime-requests", h.CreateOvertimeRequest)
}

// filerEmployee decides whose request this is: the body employee for HR, else the caller's
// own employee. self reports the ESS case.
func filerEmployee(w http.ResponseWriter, r *http.Request, bodyEmployee string) (scope RequestScope, empID uuid.UUID, self bool, ok bool) {
	scope, ok = scopeFromRequest(w, r)
	if !ok {
		return scope, uuid.Nil, false, false
	}
	if bodyEmployee != "" {
		if !requirePermission(w, scope, permAttendanceManage) {
			return scope, uuid.Nil, false, false
		}
		id, err := uuid.Parse(bodyEmployee)
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
			return scope, uuid.Nil, false, false
		}
		return scope, id, false, true
	}
	scope, empID, ok = selfEmployee(w, r)
	return scope, empID, true, ok
}

// listScope returns the employee filter for a list: the caller for ?mine=true (any staff),
// else the employee_id param for holders of the view permission.
func listScope(w http.ResponseWriter, r *http.Request) (RequestScope, *uuid.UUID, bool) {
	if r.URL.Query().Get("mine") == "true" {
		scope, id, ok := selfEmployee(w, r)
		return scope, &id, ok
	}
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return scope, nil, false
	}
	return scope, optionalUUIDParam(r, "employee_id"), true
}

func (h *AttendanceHandler) correctionError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, attendance.ErrEmployeeNotFound):
		writeError(w, http.StatusNotFound, "not_found", "employee not found")
	case errors.Is(err, attendance.ErrOvertimeApplicationsOff):
		writeError(w, http.StatusForbidden, "overtime_applications_off", err.Error())
	case errors.Is(err, attendance.ErrApprovalsUnavailable):
		writeError(w, http.StatusServiceUnavailable, "unavailable", err.Error())
	default:
		writeError(w, http.StatusBadRequest, "invalid_request", err.Error())
	}
}

type regularisationBody struct {
	EmployeeID string `json:"employee_id"`
	Date       string `json:"date"`
	CheckIn    string `json:"check_in"`
	CheckOut   string `json:"check_out"`
	Reason     string `json:"reason"`
}

func (h *AttendanceHandler) CreateRegularisation(w http.ResponseWriter, r *http.Request) {
	var b regularisationBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	scope, empID, _, ok := filerEmployee(w, r, b.EmployeeID)
	if !ok {
		return
	}
	date, err := parseDate(b.Date)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "date must be YYYY-MM-DD")
		return
	}
	in := attendance.RegularisationInput{EmployeeID: empID, Date: date, CheckIn: b.CheckIn, CheckOut: b.CheckOut, Reason: b.Reason}
	if scope.UserID != uuid.Nil {
		uid := scope.UserID
		in.RequestedBy = &uid
	}
	row, err := h.svc.CreateRegularisation(r.Context(), scope.TenantID, in)
	if err != nil {
		h.correctionError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *AttendanceHandler) ListRegularisations(w http.ResponseWriter, r *http.Request) {
	scope, empID, ok := listScope(w, r)
	if !ok {
		return
	}
	f := attendance.CorrectionFilter{EmployeeID: empID, Status: r.URL.Query().Get("status")}
	f.From, f.To = dateRangeParams(r)
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListRegularisations(r.Context(), scope.TenantID, f, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list regularisations")
		return
	}
	writePaginated(w, rows, total, p)
}

type overtimeBody struct {
	EmployeeID string          `json:"employee_id"`
	Date       string          `json:"date"`
	Hours      decimal.Decimal `json:"hours"`
	Reason     string          `json:"reason"`
}

func (h *AttendanceHandler) CreateOvertimeRequest(w http.ResponseWriter, r *http.Request) {
	var b overtimeBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	scope, empID, self, ok := filerEmployee(w, r, b.EmployeeID)
	if !ok {
		return
	}
	date, err := parseDate(b.Date)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "date must be YYYY-MM-DD")
		return
	}
	in := attendance.OvertimeInput{EmployeeID: empID, Date: date, Hours: b.Hours, Reason: b.Reason, Self: self}
	if scope.UserID != uuid.Nil {
		uid := scope.UserID
		in.RequestedBy = &uid
	}
	row, err := h.svc.CreateOvertimeRequest(r.Context(), scope.TenantID, in)
	if err != nil {
		h.correctionError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *AttendanceHandler) ListOvertimeRequests(w http.ResponseWriter, r *http.Request) {
	scope, empID, ok := listScope(w, r)
	if !ok {
		return
	}
	f := attendance.CorrectionFilter{EmployeeID: empID, Status: r.URL.Query().Get("status")}
	f.From, f.To = dateRangeParams(r)
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListOvertimeRequests(r.Context(), scope.TenantID, f, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list overtime requests")
		return
	}
	writePaginated(w, rows, total, p)
}
