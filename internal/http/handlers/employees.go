package handlers

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/Bengo-Hub/pagination"
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
		er.Post("/import", h.Import) // bulk CSV import (handler in employees_import.go)
		er.Get("/{id}", h.Get)
		er.Put("/{id}", h.Update)
		er.Patch("/{id}", h.Update)
		er.Delete("/{id}", h.Delete)
		er.Put("/{id}/salary", h.UpsertSalary)
		er.Put("/{id}/bank-accounts/{accountID}/primary", h.SetPrimaryBank)
	})
	// Bank accounts + next-of-kin are managed at top-level /hrm paths (erp-ui passes
	// the employee via emp_id query / employee body field).
	r.Route("/hrm/bank-accounts", func(br chi.Router) {
		br.Get("/", h.ListBankAccounts)
		br.Post("/", h.CreateBankAccount)
		br.Put("/{id}", h.UpdateBankAccount)
		br.Patch("/{id}", h.UpdateBankAccount)
		br.Delete("/{id}", h.DeleteBankAccount)
	})
	r.Route("/hrm/next-of-kin", func(kr chi.Router) {
		kr.Get("/", h.ListNextOfKin)
		kr.Post("/", h.CreateNextOfKin)
		kr.Put("/{id}", h.UpdateNextOfKin)
		kr.Patch("/{id}", h.UpdateNextOfKin)
		kr.Delete("/{id}", h.DeleteNextOfKin)
	})
	// Education / employment-history / disciplinary sub-records (employee_records.go).
	h.registerRecordRoutes(r)
}

type updateEmployeeBody struct {
	FirstName         *string `json:"first_name"`
	LastName          *string `json:"last_name"`
	Email             *string `json:"email"`
	Gender            *string `json:"gender"`
	NationalID        *string `json:"national_id"`
	PinNo             *string `json:"pin_no"`
	ShifOrNhifNumber  *string `json:"shif_or_nhif_number"`
	NssfNo            *string `json:"nssf_no"`
	ResidentialStatus *string `json:"residential_status"`
	EmployeeNumber    *string `json:"employee_number"`
	Terminated        *bool   `json:"terminated"`
}

// Update edits a tenant-scoped employee (PUT/PATCH /hrm/employees/{id}).
func (h *EmployeesHandler) Update(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body updateEmployeeBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.Update(r.Context(), scope.TenantID, id, employees.UpdateInput{
		FirstName:         body.FirstName,
		LastName:          body.LastName,
		Email:             body.Email,
		Gender:            body.Gender,
		NationalID:        body.NationalID,
		PinNo:             body.PinNo,
		ShifOrNhifNumber:  body.ShifOrNhifNumber,
		NssfNo:            body.NssfNo,
		ResidentialStatus: body.ResidentialStatus,
		EmployeeNumber:    body.EmployeeNumber,
		Terminated:        body.Terminated,
	})
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "employee not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// empIDFromRequest resolves the target employee id from the emp_id/employee query
// param or the employee/employee_id body field (already-decoded value).
func empIDParam(r *http.Request) *uuid.UUID {
	for _, k := range []string{"emp_id", "employee_id", "employee"} {
		if id := optionalUUIDParam(r, k); id != nil {
			return id
		}
	}
	return nil
}

// ---- Bank accounts ----

func bankAccountView(a *ent.EmployeeBankAccount) map[string]any {
	return map[string]any{
		"id":             a.ID,
		"employee":       a.EmployeeID,
		"employee_id":    a.EmployeeID,
		"bank_name":      a.BankName,
		"branch_name":    a.BranchName,
		"account_name":   a.AccountName,
		"account_number": a.AccountNumber,
		"is_primary":     a.IsPrimary,
	}
}

func (h *EmployeesHandler) ListBankAccounts(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	rows, err := h.svc.ListBankAccounts(r.Context(), scope.TenantID, empIDParam(r))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list bank accounts")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, a := range rows {
		out = append(out, bankAccountView(a))
	}
	writeJSON(w, http.StatusOK, out)
}

type bankAccountBody struct {
	Employee      string `json:"employee"`
	EmployeeID    string `json:"employee_id"`
	BankName      string `json:"bank_name"`
	BranchName    string `json:"branch_name"`
	AccountName   string `json:"account_name"`
	AccountNumber string `json:"account_number"`
	IsPrimary     bool   `json:"is_primary"`
}

func (h *EmployeesHandler) CreateBankAccount(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	var b bankAccountBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empStr := b.EmployeeID
	if empStr == "" {
		empStr = b.Employee
	}
	empID, err := uuid.Parse(empStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "employee is required")
		return
	}
	row, err := h.svc.CreateBankAccount(r.Context(), scope.TenantID, employees.BankAccountInput{
		EmployeeID: empID, BankName: b.BankName, BranchName: b.BranchName,
		AccountName: b.AccountName, AccountNumber: b.AccountNumber, IsPrimary: b.IsPrimary,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, bankAccountView(row))
}

func (h *EmployeesHandler) UpdateBankAccount(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b bankAccountBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateBankAccount(r.Context(), scope.TenantID, id, employees.BankAccountInput{
		BankName: b.BankName, BranchName: b.BranchName,
		AccountName: b.AccountName, AccountNumber: b.AccountNumber,
	})
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "bank account not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, bankAccountView(row))
}

func (h *EmployeesHandler) DeleteBankAccount(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteBankAccount(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Next of kin ----

func kinView(k *ent.NextOfKin) map[string]any {
	v := map[string]any{
		"id":          k.ID,
		"employee":    k.EmployeeID,
		"employee_id": k.EmployeeID,
		"name":        k.FullName,
		"full_name":   k.FullName,
	}
	if k.Relationship != nil {
		v["relationship"] = *k.Relationship
	}
	if k.Phone != nil {
		v["phone_number"] = *k.Phone
		v["phone"] = *k.Phone
	}
	if k.Email != nil {
		v["email"] = *k.Email
	}
	if k.Address != nil {
		v["address"] = *k.Address
	}
	return v
}

func (h *EmployeesHandler) ListNextOfKin(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	rows, err := h.svc.ListNextOfKin(r.Context(), scope.TenantID, empIDParam(r))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list next of kin")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, k := range rows {
		out = append(out, kinView(k))
	}
	writeJSON(w, http.StatusOK, out)
}

type kinBody struct {
	Employee     string `json:"employee"`
	EmployeeID   string `json:"employee_id"`
	Name         string `json:"name"`
	FullName     string `json:"full_name"`
	Relationship string `json:"relationship"`
	PhoneNumber  string `json:"phone_number"`
	Phone        string `json:"phone"`
	Email        string `json:"email"`
	Address      string `json:"address"`
}

func (b kinBody) name() string {
	if b.Name != "" {
		return b.Name
	}
	return b.FullName
}

func (b kinBody) phone() string {
	if b.PhoneNumber != "" {
		return b.PhoneNumber
	}
	return b.Phone
}

func (h *EmployeesHandler) CreateNextOfKin(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	var b kinBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empStr := b.EmployeeID
	if empStr == "" {
		empStr = b.Employee
	}
	empID, err := uuid.Parse(empStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "employee is required")
		return
	}
	row, err := h.svc.CreateNextOfKin(r.Context(), scope.TenantID, employees.NextOfKinInput{
		EmployeeID: empID, FullName: b.name(), Relationship: b.Relationship,
		Phone: b.phone(), Email: b.Email, Address: b.Address,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, kinView(row))
}

func (h *EmployeesHandler) UpdateNextOfKin(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b kinBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateNextOfKin(r.Context(), scope.TenantID, id, employees.NextOfKinInput{
		FullName: b.name(), Relationship: b.Relationship,
		Phone: b.phone(), Email: b.Email, Address: b.Address,
	})
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "next of kin not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, kinView(row))
}

func (h *EmployeesHandler) DeleteNextOfKin(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteNextOfKin(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *EmployeesHandler) List(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if !requirePermission(w, scope, permEmployeeView) {
		return
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.List(r.Context(), employees.ListParams{
		TenantID: scope.TenantID,
		OutletID: scope.OutletID,
		Limit:    p.Limit,
		Offset:   p.Offset,
	})
	if err != nil {
		h.log.Error("list employees", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list employees")
		return
	}
	writePaginated(w, rows, total, p)
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
	if errors.Is(err, employees.ErrNameRequired) {
		writeError(w, http.StatusBadRequest, "validation_failed", "first_name and last_name are required")
		return
	}
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
