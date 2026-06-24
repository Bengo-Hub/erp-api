package handlers

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
)

// employee_records.go — HTTP CRUD for the HR-owned employee sub-records (education,
// employment history, disciplinary). Mounted under /hrm/* alongside next-of-kin.

func (h *EmployeesHandler) registerRecordRoutes(r chi.Router) {
	r.Route("/hrm/employee-education", func(er chi.Router) {
		er.Get("/", h.ListEducation)
		er.Post("/", h.CreateEducation)
		er.Put("/{id}", h.UpdateEducation)
		er.Patch("/{id}", h.UpdateEducation)
		er.Delete("/{id}", h.DeleteEducation)
	})
	r.Route("/hrm/employment-history", func(er chi.Router) {
		er.Get("/", h.ListEmploymentHistory)
		er.Post("/", h.CreateEmploymentHistory)
		er.Put("/{id}", h.UpdateEmploymentHistory)
		er.Patch("/{id}", h.UpdateEmploymentHistory)
		er.Delete("/{id}", h.DeleteEmploymentHistory)
	})
	r.Route("/hrm/employee-disciplinary", func(er chi.Router) {
		er.Get("/", h.ListDisciplinary)
		er.Post("/", h.CreateDisciplinary)
		er.Put("/{id}", h.UpdateDisciplinary)
		er.Patch("/{id}", h.UpdateDisciplinary)
		er.Delete("/{id}", h.DeleteDisciplinary)
	})
}

func parseDatePtr(s string) *time.Time {
	if s == "" {
		return nil
	}
	for _, layout := range []string{"2006-01-02", time.RFC3339} {
		if t, err := time.Parse(layout, s); err == nil {
			return &t
		}
	}
	return nil
}

func idParam(w http.ResponseWriter, r *http.Request) (uuid.UUID, bool) {
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return uuid.Nil, false
	}
	return id, true
}

func bodyEmployeeID(w http.ResponseWriter, raw string) (uuid.UUID, bool) {
	id, err := uuid.Parse(raw)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "employee is required")
		return uuid.Nil, false
	}
	return id, true
}

// ---- Education ----

type educationBody struct {
	Employee       string `json:"employee"`
	EmployeeID     string `json:"employee_id"`
	Institution    string `json:"institution"`
	Qualification  string `json:"qualification"`
	FieldOfStudy   string `json:"field_of_study"`
	Grade          string `json:"grade"`
	CertificateURL string `json:"certificate_url"`
	StartDate      string `json:"start_date"`
	EndDate        string `json:"end_date"`
}

func (b educationBody) empID() string {
	if b.EmployeeID != "" {
		return b.EmployeeID
	}
	return b.Employee
}

func (h *EmployeesHandler) ListEducation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	rows, err := h.svc.ListEducation(r.Context(), scope.TenantID, empIDParam(r))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list education")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

func (h *EmployeesHandler) CreateEducation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	var b educationBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, ok := bodyEmployeeID(w, b.empID())
	if !ok {
		return
	}
	row, err := h.svc.CreateEducation(r.Context(), scope.TenantID, employees.EducationInput{
		EmployeeID: empID, Institution: b.Institution, Qualification: b.Qualification,
		FieldOfStudy: b.FieldOfStudy, Grade: b.Grade, CertificateURL: b.CertificateURL,
		StartDate: parseDatePtr(b.StartDate), EndDate: parseDatePtr(b.EndDate),
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *EmployeesHandler) UpdateEducation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	var b educationBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateEducation(r.Context(), scope.TenantID, id, employees.EducationInput{
		Institution: b.Institution, Qualification: b.Qualification, FieldOfStudy: b.FieldOfStudy,
		Grade: b.Grade, CertificateURL: b.CertificateURL,
		StartDate: parseDatePtr(b.StartDate), EndDate: parseDatePtr(b.EndDate),
	})
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "education record not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *EmployeesHandler) DeleteEducation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	if err := h.svc.DeleteEducation(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Employment history ----

type employmentBody struct {
	Employee         string `json:"employee"`
	EmployeeID       string `json:"employee_id"`
	Employer         string `json:"employer"`
	Designation      string `json:"designation"`
	ReasonForLeaving string `json:"reason_for_leaving"`
	StartDate        string `json:"start_date"`
	EndDate          string `json:"end_date"`
}

func (b employmentBody) empID() string {
	if b.EmployeeID != "" {
		return b.EmployeeID
	}
	return b.Employee
}

func (h *EmployeesHandler) ListEmploymentHistory(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	rows, err := h.svc.ListEmploymentHistory(r.Context(), scope.TenantID, empIDParam(r))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list employment history")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

func (h *EmployeesHandler) CreateEmploymentHistory(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	var b employmentBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, ok := bodyEmployeeID(w, b.empID())
	if !ok {
		return
	}
	row, err := h.svc.CreateEmploymentHistory(r.Context(), scope.TenantID, employees.EmploymentHistoryInput{
		EmployeeID: empID, Employer: b.Employer, Designation: b.Designation,
		ReasonForLeaving: b.ReasonForLeaving,
		StartDate:        parseDatePtr(b.StartDate), EndDate: parseDatePtr(b.EndDate),
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *EmployeesHandler) UpdateEmploymentHistory(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	var b employmentBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateEmploymentHistory(r.Context(), scope.TenantID, id, employees.EmploymentHistoryInput{
		Employer: b.Employer, Designation: b.Designation, ReasonForLeaving: b.ReasonForLeaving,
		StartDate: parseDatePtr(b.StartDate), EndDate: parseDatePtr(b.EndDate),
	})
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "employment history not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *EmployeesHandler) DeleteEmploymentHistory(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	if err := h.svc.DeleteEmploymentHistory(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Disciplinary ----

type disciplinaryBody struct {
	Employee     string `json:"employee"`
	EmployeeID   string `json:"employee_id"`
	Category     string `json:"category"`
	Description  string `json:"description"`
	ActionTaken  string `json:"action_taken"`
	Status       string `json:"status"`
	DocumentURL  string `json:"document_url"`
	IncidentDate string `json:"incident_date"`
}

func (b disciplinaryBody) empID() string {
	if b.EmployeeID != "" {
		return b.EmployeeID
	}
	return b.Employee
}

func (h *EmployeesHandler) ListDisciplinary(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	rows, err := h.svc.ListDisciplinary(r.Context(), scope.TenantID, empIDParam(r))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list disciplinary")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

func (h *EmployeesHandler) CreateDisciplinary(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	var b disciplinaryBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, ok := bodyEmployeeID(w, b.empID())
	if !ok {
		return
	}
	row, err := h.svc.CreateDisciplinary(r.Context(), scope.TenantID, employees.DisciplinaryInput{
		EmployeeID: empID, Category: b.Category, Description: b.Description, ActionTaken: b.ActionTaken,
		Status: b.Status, DocumentURL: b.DocumentURL, IncidentDate: parseDatePtr(b.IncidentDate),
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *EmployeesHandler) UpdateDisciplinary(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	var b disciplinaryBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateDisciplinary(r.Context(), scope.TenantID, id, employees.DisciplinaryInput{
		Category: b.Category, Description: b.Description, ActionTaken: b.ActionTaken,
		Status: b.Status, DocumentURL: b.DocumentURL, IncidentDate: parseDatePtr(b.IncidentDate),
	})
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "disciplinary record not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *EmployeesHandler) DeleteDisciplinary(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	if err := h.svc.DeleteDisciplinary(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
