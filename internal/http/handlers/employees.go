package handlers

import (
	"encoding/json"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
)

// HRM RBAC permission codes (bare codenames matching auth-api perms).
const (
	permEmployeeView   = "hrm.employee.view"
	permEmployeeManage = "hrm.employee.manage"
)

// EmployeesHandler serves /api/v1/hrm/employees.
type EmployeesHandler struct {
	log *zap.Logger
	svc *employees.Service
}

func NewEmployeesHandler(log *zap.Logger, svc *employees.Service) *EmployeesHandler {
	return &EmployeesHandler{log: log.Named("hrm.employees"), svc: svc}
}

func (h *EmployeesHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/employees", func(er chi.Router) {
		er.Get("/", h.List)
		er.Post("/", h.Create)
		er.Get("/{id}", h.Get)
		er.Delete("/{id}", h.Delete)
		er.Put("/{id}/salary", h.UpsertSalary)
		er.Put("/{id}/bank-accounts/{accountID}/primary", h.SetPrimaryBank)
	})
}

func (h *EmployeesHandler) List(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if !requirePermission(w, scope, permEmployeeView) {
		return
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	offset, _ := strconv.Atoi(r.URL.Query().Get("offset"))
	rows, total, err := h.svc.List(r.Context(), employees.ListParams{
		TenantID: scope.TenantID,
		OutletID: scope.OutletID,
		Limit:    limit,
		Offset:   offset,
	})
	if err != nil {
		h.log.Error("list employees", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list employees")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{
		"data":  rows,
		"count": total,
	})
}

func (h *EmployeesHandler) Get(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if !requirePermission(w, scope, permEmployeeView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.Get(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "employee not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch employee")
		return
	}
	writeJSON(w, http.StatusOK, row)
}

type createEmployeeBody struct {
	OutletID          string `json:"outlet_id"`
	UserID            string `json:"user_id"`
	EmployeeNumber    string `json:"employee_number"`
	FirstName         string `json:"first_name"`
	LastName          string `json:"last_name"`
	Email             string `json:"email"`
	Gender            string `json:"gender"`
	NationalID        string `json:"national_id"`
	PinNo             string `json:"pin_no"`
	ShifOrNhifNumber  string `json:"shif_or_nhif_number"`
	NssfNo            string `json:"nssf_no"`
	ResidentialStatus string `json:"residential_status"`
}

func (h *EmployeesHandler) Create(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	var body createEmployeeBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in := employees.CreateInput{
		EmployeeNumber:    body.EmployeeNumber,
		FirstName:         body.FirstName,
		LastName:          body.LastName,
		Email:             body.Email,
		Gender:            body.Gender,
		NationalID:        body.NationalID,
		PinNo:             body.PinNo,
		ShifOrNhifNumber:  body.ShifOrNhifNumber,
		NssfNo:            body.NssfNo,
		ResidentialStatus: body.ResidentialStatus,
	}
	// Restricted users default the new employee to their own outlet.
	if body.OutletID != "" {
		if oid, err := uuid.Parse(body.OutletID); err == nil {
			in.OutletID = &oid
		}
	} else if scope.OutletID != uuid.Nil {
		oid := scope.OutletID
		in.OutletID = &oid
	}
	if body.UserID != "" {
		if uid, err := uuid.Parse(body.UserID); err == nil {
			in.UserID = &uid
		}
	}
	row, err := h.svc.Create(r.Context(), scope.TenantID, in)
	if err != nil {
		h.log.Warn("create employee", zap.Error(err))
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *EmployeesHandler) Delete(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.SoftDelete(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

type upsertSalaryBody struct {
	MonthlySalary string `json:"monthly_salary"`
	PayMode       string `json:"pay_mode"`
	IncomeTax     string `json:"income_tax"`
	Currency      string `json:"currency"`
}

func (h *EmployeesHandler) UpsertSalary(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body upsertSalaryBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	monthly, err := decimal.NewFromString(body.MonthlySalary)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid monthly_salary (must be a decimal string)")
		return
	}
	row, err := h.svc.UpsertSalary(r.Context(), scope.TenantID, id, monthly, body.PayMode, body.IncomeTax, body.Currency)
	if err != nil {
		writeError(w, http.StatusBadRequest, "salary_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *EmployeesHandler) SetPrimaryBank(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	accountID, err := uuid.Parse(chi.URLParam(r, "accountID"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid account id")
		return
	}
	if err := h.svc.SetPrimaryBankAccount(r.Context(), scope.TenantID, id, accountID); err != nil {
		writeError(w, http.StatusBadRequest, "primary_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}
