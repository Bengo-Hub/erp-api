package handlers

import (
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"path/filepath"
	"strings"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	platformauth "github.com/Bengo-Hub/erp-api/internal/platform/auth"
	"github.com/Bengo-Hub/erp-api/internal/platform/media"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

// HRM RBAC permission codes (bare codenames matching auth-api perms).
const (
	permEmployeeView   = "hrm.employee.view"
	permEmployeeManage = "hrm.employee.manage"
)

// EmployeesHandler serves /api/v1/hrm/employees.
type EmployeesHandler struct {
	log      *zap.Logger
	svc      *employees.Service
	treasury *treasury.Client
	media    *media.Store
	branding *platformauth.BrandingClient
	// attendance serves the employee device PIN (employees_device_pin.go).
	attendance *attendance.Service
}

func NewEmployeesHandler(log *zap.Logger, svc *employees.Service) *EmployeesHandler {
	return &EmployeesHandler{log: log.Named("hrm.employees"), svc: svc}
}

// WithTreasury injects the treasury S2S client used to verify employee bank accounts (Paystack).
func (h *EmployeesHandler) WithTreasury(c *treasury.Client) *EmployeesHandler {
	h.treasury = c
	return h
}

// WithMedia wires the media store so HR documents / generated contracts can be stored. Optional.
func (h *EmployeesHandler) WithMedia(m *media.Store) *EmployeesHandler {
	h.media = m
	return h
}

// WithBranding wires the auth-api branding client so contracts render on the tenant letterhead.
func (h *EmployeesHandler) WithBranding(b *platformauth.BrandingClient) *EmployeesHandler {
	h.branding = b
	return h
}

func (h *EmployeesHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/employees", func(er chi.Router) {
		er.Get("/", h.List)
		er.Get("/lookup", h.Lookup) // active staff for other services' pickers (employees_lookup.go)
		er.Post("/", h.Create)
		er.Post("/renumber", h.Renumber) // re-issue SLUG/YYYY/### staff numbers to all employees
		er.Post("/import", h.Import)     // bulk CSV import (handler in employees_import.go)
		er.Get("/{id}", h.Get)
		er.Put("/{id}", h.Update)
		er.Patch("/{id}", h.Update)
		er.Delete("/{id}", h.Delete)
		er.Put("/{id}/salary", h.UpsertSalary)
		er.Put("/{id}/device-pin", h.SetDevicePIN) // biometric user PIN (employees_device_pin.go)
		er.Put("/{id}/bank-accounts/{accountID}/primary", h.SetPrimaryBank)
		// HR documents (upload / list / stream).
		er.Post("/{id}/documents", h.UploadDocument)
		er.Get("/{id}/documents", h.ListDocuments)
		er.Get("/{id}/documents/{docId}/file", h.DownloadDocument)
		// Employment-contract terms (editable, tenant-scoped) + branded PDF.
		er.Get("/{id}/contract/terms", h.GetContractTerms)
		er.Put("/{id}/contract/terms", h.PutContractTerms)
		er.Get("/{id}/contract/pdf", h.ContractPDF)
		er.Post("/{id}/contract/generate", h.GenerateContract)
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
	// Bank list + account verification (proxied to treasury S2S Paystack) so employee bank
	// accounts are verified before saving — accurate payroll payouts.
	r.Get("/hrm/banks/{country}", h.ListBanks)
	r.Get("/hrm/banks/resolve", h.ResolveBankAccount)
	// Employee ↔ project allocations (consultants on multiple projects, % / fixed split).
	r.Route("/hrm/project-allocations", func(pa chi.Router) {
		pa.Get("/", h.ListAllocations)
		pa.Post("/", h.CreateAllocation)
		pa.Put("/{id}", h.UpdateAllocation)
		pa.Patch("/{id}", h.UpdateAllocation)
		pa.Delete("/{id}", h.DeleteAllocation)
	})
	// Education / employment-history / disciplinary sub-records (employee_records.go).
	h.registerRecordRoutes(r)
}

// Renumber re-issues SLUG/YYYY/### staff numbers to all of the tenant's employees (admin action).
func (h *EmployeesHandler) Renumber(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	n, err := h.svc.RenumberEmployees(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "renumber_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"status": "ok", "renumbered": n})
}

// employeeHRFields are the employment details saved to hr_details on create and update. The
// employee form sends department / job_title; API clients may send the *_id names. "" clears.
type employeeHRFields struct {
	Department     *string `json:"department"`
	DepartmentID   *string `json:"department_id"`
	JobTitle       *string `json:"job_title"`
	JobTitleID     *string `json:"job_title_id"`
	ReportsToID    *string `json:"reports_to_id"`
	EmploymentType *string `json:"employment_type"`
	DateJoined     *string `json:"date_joined"`
}

// hrInput validates and converts the HR fields.
func (b employeeHRFields) hrInput() (employees.HRInput, error) {
	var in employees.HRInput
	pick := func(a, b *string) *string {
		if b != nil {
			return b
		}
		return a
	}
	for _, f := range []struct {
		raw  *string
		dst  **uuid.UUID
		name string
	}{
		{pick(b.Department, b.DepartmentID), &in.DepartmentID, "department_id"},
		{pick(b.JobTitle, b.JobTitleID), &in.JobTitleID, "job_title_id"},
		{b.ReportsToID, &in.ReportsToID, "reports_to_id"},
	} {
		if f.raw == nil {
			continue
		}
		id := uuid.Nil
		if s := strings.TrimSpace(*f.raw); s != "" {
			var err error
			if id, err = uuid.Parse(s); err != nil {
				return in, fmt.Errorf("%s must be a UUID or empty", f.name)
			}
		}
		*f.dst = &id
	}
	in.EmploymentType = b.EmploymentType
	if b.DateJoined != nil && strings.TrimSpace(*b.DateJoined) != "" {
		raw := strings.TrimSpace(*b.DateJoined)
		if len(raw) > 10 {
			raw = raw[:10]
		}
		d, err := time.Parse("2006-01-02", raw)
		if err != nil {
			return in, fmt.Errorf("date_joined must be YYYY-MM-DD")
		}
		in.DateJoined = &d
	}
	return in, nil
}

type updateEmployeeBody struct {
	employeeHRFields
	// KraPin is the employee form's name for pin_no.
	KraPin *string `json:"kra_pin"`
	// PhoneNumber is kept in contact_details; "" clears it.
	PhoneNumber       *string `json:"phone_number"`
	FirstName         *string `json:"first_name"`
	LastName          *string `json:"last_name"`
	Email             *string `json:"email"`
	Gender            *string `json:"gender"`
	NationalID        *string `json:"national_id"`
	PinNo             *string `json:"pin_no"`
	ShifOrNhifNumber  *string `json:"shif_or_nhif_number"`
	NssfNo            *string `json:"nssf_no"`
	ResidentialStatus *string `json:"residential_status"`
	// DateOfBirth is YYYY-MM-DD; "" clears it.
	DateOfBirth    *string `json:"date_of_birth"`
	EmployeeNumber *string `json:"employee_number"`
	Terminated        *bool   `json:"terminated"`
	IsDirector        *bool   `json:"is_director"`
	IsShareholder     *bool   `json:"is_shareholder"`
	// WorkShiftID is the standard work shift (weekly working hours); "" clears it.
	WorkShiftID *string `json:"work_shift_id"`
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
	var workShiftID *uuid.UUID
	if body.WorkShiftID != nil {
		shift := uuid.Nil
		if raw := strings.TrimSpace(*body.WorkShiftID); raw != "" {
			if shift, err = uuid.Parse(raw); err != nil {
				writeError(w, http.StatusBadRequest, "bad_request", "work_shift_id must be a UUID or empty")
				return
			}
		}
		workShiftID = &shift
	}
	hr, err := body.hrInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	if body.PinNo == nil {
		body.PinNo = body.KraPin
	}
	var dob *time.Time
	if body.DateOfBirth != nil {
		d := time.Time{}
		if raw := strings.TrimSpace(*body.DateOfBirth); raw != "" {
			if d, err = parseDate(raw); err != nil {
				writeError(w, http.StatusBadRequest, "bad_request", "date_of_birth must be YYYY-MM-DD")
				return
			}
		}
		dob = &d
	}
	row, err := h.svc.Update(r.Context(), scope.TenantID, id, employees.UpdateInput{
		DateOfBirth:       dob,
		WorkShiftID:       workShiftID,
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
		IsDirector:        body.IsDirector,
		IsShareholder:     body.IsShareholder,
	})
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "employee not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	if err := h.svc.UpsertHR(r.Context(), scope.TenantID, id, hr); err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	if body.PhoneNumber != nil {
		if err := h.svc.SetPhone(r.Context(), scope.TenantID, id, *body.PhoneNumber); err != nil {
			writeError(w, http.StatusBadRequest, "update_failed", err.Error())
			return
		}
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
	writePagedSlice(w, out, pagination.Parse(r))
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
	writePagedSlice(w, out, pagination.Parse(r))
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
	views, err := h.svc.Enrich(r.Context(), scope.TenantID, rows)
	if err != nil {
		h.log.Error("enrich employees", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to enrich employees")
		return
	}
	writePaginated(w, views, total, p)
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
	views, err := h.svc.Enrich(r.Context(), scope.TenantID, []*ent.Employee{row})
	if err != nil || len(views) == 0 {
		writeJSON(w, http.StatusOK, row)
		return
	}
	writeJSON(w, http.StatusOK, views[0])
}

type createEmployeeBody struct {
	employeeHRFields
	KraPin            string `json:"kra_pin"`
	PhoneNumber       string `json:"phone_number"` // kept in contact_details
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
	IsDirector        bool   `json:"is_director"`
	IsShareholder     bool   `json:"is_shareholder"`
	DateOfBirth       string `json:"date_of_birth"` // YYYY-MM-DD, optional
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
	hr, err := body.hrInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	if body.PinNo == "" {
		body.PinNo = body.KraPin
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
		IsDirector:        body.IsDirector,
		IsShareholder:     body.IsShareholder,
	}
	if raw := strings.TrimSpace(body.DateOfBirth); raw != "" {
		d, err := parseDate(raw)
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "date_of_birth must be YYYY-MM-DD")
			return
		}
		in.DateOfBirth = &d
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
	if err := h.svc.UpsertHR(r.Context(), scope.TenantID, row.ID, hr); err != nil {
		// The person exists; report the HR detail problem without losing the new record.
		writeJSON(w, http.StatusCreated, map[string]any{"employee": row, "warning": err.Error()})
		return
	}
	if err := h.svc.SetPhone(r.Context(), scope.TenantID, row.ID, body.PhoneNumber); err != nil {
		writeJSON(w, http.StatusCreated, map[string]any{"employee": row, "warning": err.Error()})
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
	// KRA relief inputs (optional; decimal strings, default 0). The engine applies the statutory caps.
	InsurancePremium    string `json:"insurance_premium"`
	PensionContribution string `json:"pension_contribution"`
	MortgageInterest    string `json:"mortgage_interest"`
	DisabilityExempt    bool   `json:"disability_exempt"`
	// Preferred net-pay disbursement channel (optional; default bank_transfer).
	PreferredPayoutMethod string `json:"preferred_payout_method"`
	PayoutPhone           string `json:"payout_phone"`
}

// decimalOrZero parses a decimal string, returning zero for blank/invalid input (used for
// optional numeric form fields that default to 0).
func decimalOrZero(s string) decimal.Decimal {
	if s == "" {
		return decimal.Zero
	}
	d, err := decimal.NewFromString(s)
	if err != nil {
		return decimal.Zero
	}
	return d
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
	// Optional relief amounts default to 0 when blank/unparseable.
	reliefs := employees.SalaryReliefInput{
		InsurancePremium:      decimalOrZero(body.InsurancePremium),
		PensionContribution:   decimalOrZero(body.PensionContribution),
		MortgageInterest:      decimalOrZero(body.MortgageInterest),
		DisabilityExempt:      body.DisabilityExempt,
		PreferredPayoutMethod: body.PreferredPayoutMethod,
		PayoutPhone:           body.PayoutPhone,
	}
	row, err := h.svc.UpsertSalary(r.Context(), scope.TenantID, id, monthly, body.PayMode, body.IncomeTax, body.Currency, reliefs)
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

// ---- Employee HR documents ----

func (h *EmployeesHandler) documentView(d *ent.EmployeeDocument) map[string]any {
	v := map[string]any{
		"id":          d.ID,
		"employee":    d.EmployeeID,
		"employee_id": d.EmployeeID,
		"title":       d.Title,
		"created_at":  d.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}
	if d.DocumentType != nil {
		v["document_type"] = *d.DocumentType
	}
	if d.FileURL != nil {
		v["file_url"] = *d.FileURL
		if h.media.Enabled() {
			v["file_download_url"] = h.media.URL(*d.FileURL)
		}
	}
	return v
}

// UploadDocument stores a multipart HR document (file + title + document_type) in the per-tenant
// media store and records the EmployeeDocument row.
func (h *EmployeesHandler) UploadDocument(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	if !h.media.Enabled() {
		writeError(w, http.StatusServiceUnavailable, "media_unavailable", "media storage not configured")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := r.ParseMultipartForm(10 << 20); err != nil { // 10 MiB cap
		writeError(w, http.StatusBadRequest, "bad_request", "invalid multipart form")
		return
	}
	title := strings.TrimSpace(r.FormValue("title"))
	if title == "" {
		writeError(w, http.StatusBadRequest, "bad_request", "title is required")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "missing 'file' field")
		return
	}
	defer func() { _ = file.Close() }()
	data, err := io.ReadAll(file)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "failed to read file")
		return
	}
	rel, err := h.media.SaveEmployeeDocument(r.Context(), scope.TenantID, id, header.Filename, data)
	if err != nil {
		writeError(w, http.StatusBadRequest, "upload_failed", err.Error())
		return
	}
	row, err := h.svc.CreateDocument(r.Context(), scope.TenantID, employees.DocumentInput{
		EmployeeID:   id,
		Title:        title,
		DocumentType: strings.TrimSpace(r.FormValue("document_type")),
		FileURL:      rel,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, h.documentView(row))
}

// ListDocuments lists a tenant-scoped employee's HR documents.
func (h *EmployeesHandler) ListDocuments(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	rows, err := h.svc.ListDocuments(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list documents")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, d := range rows {
		out = append(out, h.documentView(d))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

// DownloadDocument streams the stored bytes of an employee document (Content-Type by extension).
func (h *EmployeesHandler) DownloadDocument(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	if !h.media.Enabled() {
		writeError(w, http.StatusServiceUnavailable, "media_unavailable", "media storage not configured")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	docID, err := uuid.Parse(chi.URLParam(r, "docId"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid document id")
		return
	}
	doc, err := h.svc.GetDocument(r.Context(), scope.TenantID, id, docID)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "document not found")
		return
	}
	if err != nil || doc.FileURL == nil || *doc.FileURL == "" {
		writeError(w, http.StatusNotFound, "not_found", "document file not found")
		return
	}
	body, mimeType, err := h.media.Get(r.Context(), *doc.FileURL)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "document file not found")
		return
	}
	if mimeType == "" {
		mimeType = "application/octet-stream"
	}
	streamDownload(w, body, mimeType, filepath.Base(*doc.FileURL))
}

// ---- Employment contract terms ----

// contractTermsInput resolves branding + employee into a ContractTermsInput for the given type.
func (h *EmployeesHandler) contractTermsInput(scope RequestScope, emp *ent.Employee, empType, jobTitle string) employees.ContractTermsInput {
	in := employees.ContractTermsInput{
		EmployeeName:   employeeFullName(emp),
		JobTitle:       jobTitle,
		IsDirector:     emp.IsDirector,
		IsShareholder:  emp.IsShareholder,
		EmploymentType: empType,
	}
	if h.branding != nil {
		if slug := h.svc.TenantSlug(scope.Ctx, scope.TenantID); slug != "" {
			if b, err := h.branding.GetBySlug(scope.Ctx, slug); err == nil && b != nil {
				in.CompanyName = b.Name
				in.CompanyAddress = b.Address
				in.CompanyKraPin = b.KraPin
				in.PrimaryColor = b.PrimaryColor
				in.LogoURL = b.LogoURL
			}
		}
	}
	return in
}

func employeeFullName(emp *ent.Employee) string {
	name := strings.TrimSpace(emp.FirstName + " " + emp.LastName)
	return name
}

// resolvedTermsHTML returns the stored terms_html for the employee's contract, or the auto-
// generated default for the requested type when none is stored.
func (h *EmployeesHandler) resolvedTermsHTML(scope RequestScope, emp *ent.Employee, empType, jobTitle string) (string, error) {
	stored, err := h.svc.StoredContractTerms(scope.Ctx, scope.TenantID, emp.ID)
	if err != nil {
		return "", err
	}
	if strings.TrimSpace(stored) != "" {
		return stored, nil
	}
	return employees.BuildDefaultTermsHTML(h.contractTermsInput(scope, emp, empType, jobTitle)), nil
}

// GetContractTerms returns the stored contract terms_html if set, else the auto-generated default.
func (h *EmployeesHandler) GetContractTerms(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	emp, err := h.svc.Get(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "employee not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch employee")
		return
	}
	empType := employees.NormalizeEmploymentType(r.URL.Query().Get("type"), emp.IsDirector, emp.IsShareholder)
	termsHTML, err := h.resolvedTermsHTML(scope, emp, empType, r.URL.Query().Get("role"))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to resolve terms")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"terms_html": termsHTML, "employment_type": empType})
}

type contractTermsBody struct {
	TermsHTML string `json:"terms_html"`
}

// PutContractTerms saves edited HTML onto the employee's Contract (creating one if none).
func (h *EmployeesHandler) PutContractTerms(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body contractTermsBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	if strings.TrimSpace(body.TermsHTML) == "" {
		writeError(w, http.StatusBadRequest, "bad_request", "terms_html is required")
		return
	}
	c, err := h.svc.SaveContractTerms(r.Context(), scope.TenantID, id, body.TermsHTML)
	if err != nil {
		writeError(w, http.StatusBadRequest, "save_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"id": c.ID, "employee_id": c.EmployeeID, "terms_html": c.TermsHTML})
}

// ContractPDF renders the (stored or default) terms into a branded PDF and streams it.
func (h *EmployeesHandler) ContractPDF(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	body, filename, err := h.contractPDFBytes(scope, id, r.URL.Query().Get("type"), r.URL.Query().Get("role"))
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "employee not found")
		return
	}
	if err != nil {
		h.log.Error("contract pdf", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate contract")
		return
	}
	streamDownload(w, body, "application/pdf", filename)
}

// contractPDFBytes resolves the employee + terms and renders the branded contract PDF bytes.
func (h *EmployeesHandler) contractPDFBytes(scope RequestScope, id uuid.UUID, typeParam, jobTitle string) ([]byte, string, error) {
	emp, err := h.svc.Get(scope.Ctx, scope.TenantID, id)
	if err != nil {
		return nil, "", err
	}
	empType := employees.NormalizeEmploymentType(typeParam, emp.IsDirector, emp.IsShareholder)
	termsHTML, err := h.resolvedTermsHTML(scope, emp, empType, jobTitle)
	if err != nil {
		return nil, "", err
	}
	body, err := employees.RenderContractPDF(h.contractTermsInput(scope, emp, empType, jobTitle), termsHTML)
	if err != nil {
		return nil, "", err
	}
	return body, "employment-contract-" + emp.ID.String()[:8] + ".pdf", nil
}

// GenerateContract renders the branded PDF and stores it as an EmployeeDocument.
func (h *EmployeesHandler) GenerateContract(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	if !h.media.Enabled() {
		writeError(w, http.StatusServiceUnavailable, "media_unavailable", "media storage not configured")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	body, filename, err := h.contractPDFBytes(scope, id, r.URL.Query().Get("type"), r.URL.Query().Get("role"))
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "employee not found")
		return
	}
	if err != nil {
		h.log.Error("contract generate", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate contract")
		return
	}
	rel, err := h.media.SaveEmployeeDocument(r.Context(), scope.TenantID, id, filename, body)
	if err != nil {
		writeError(w, http.StatusBadRequest, "save_failed", err.Error())
		return
	}
	row, err := h.svc.CreateDocument(r.Context(), scope.TenantID, employees.DocumentInput{
		EmployeeID:   id,
		Title:        "Employment Terms & Contract",
		DocumentType: "employment_contract",
		FileURL:      rel,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, h.documentView(row))
}
