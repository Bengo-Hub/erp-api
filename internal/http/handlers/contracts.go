package handlers

import (
	"context"
	"encoding/json"
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/contracts"
)

// ContractsHandler serves /api/v1/hrm/contracts. Reuses the employee RBAC codes.
type ContractsHandler struct {
	log *zap.Logger
	svc *contracts.Service
}

func NewContractsHandler(log *zap.Logger, svc *contracts.Service) *ContractsHandler {
	return &ContractsHandler{log: log.Named("hrm.contracts"), svc: svc}
}

func (h *ContractsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/contracts", func(cr chi.Router) {
		cr.Get("/", h.List)
		cr.Post("/", h.Create)
		cr.Get("/{id}", h.Get)
		cr.Put("/{id}", h.Update)
		cr.Patch("/{id}", h.Update)
		cr.Delete("/{id}", h.Delete)
	})
}

// contractView is the erp-ui-facing shape.
type contractView struct {
	ID                uuid.UUID `json:"id"`
	Employee          uuid.UUID `json:"employee"`
	EmployeeID        uuid.UUID `json:"employee_id"`
	EmployeeName      string    `json:"employee_name,omitempty"`
	EmployeeNumber    string    `json:"employee_number,omitempty"`
	ContractStartDate string    `json:"contract_start_date,omitempty"`
	ContractEndDate   string    `json:"contract_end_date,omitempty"`
	PayType           string    `json:"pay_type,omitempty"`
	ContractType      string    `json:"contract_type,omitempty"`
	Salary            string    `json:"salary"`
	Status            string    `json:"status,omitempty"`
	ContractDuration  int       `json:"contract_duration"`
	CreatedAt         string    `json:"created_at,omitempty"`
}

func (h *ContractsHandler) view(ctx context.Context, tenantID uuid.UUID, c *ent.Contract) contractView {
	v := contractView{
		ID:               c.ID,
		Employee:         c.EmployeeID,
		EmployeeID:       c.EmployeeID,
		PayType:          c.ContractType,
		ContractType:     c.ContractType,
		Salary:           c.Salary.String(),
		Status:           c.Status,
		ContractDuration: c.DurationMonths,
		CreatedAt:        c.CreatedAt.Format("2006-01-02T15:04:05Z07:00"),
	}
	if c.StartDate != nil {
		v.ContractStartDate = c.StartDate.Format("2006-01-02")
	}
	if c.EndDate != nil {
		v.ContractEndDate = c.EndDate.Format("2006-01-02")
	}
	v.EmployeeName, v.EmployeeNumber = h.svc.EmployeeName(ctx, tenantID, c.EmployeeID)
	return v
}

// contractBody is the create/update payload. erp-ui uses contract_start_date /
// contract_end_date / pay_type; legacy callers may use start_date / contract_type.
type contractBody struct {
	Employee          string `json:"employee"`
	EmployeeID        string `json:"employee_id"`
	ContractStartDate string `json:"contract_start_date"`
	ContractEndDate   string `json:"contract_end_date"`
	StartDate         string `json:"start_date"`
	EndDate           string `json:"end_date"`
	PayType           string `json:"pay_type"`
	ContractType      string `json:"contract_type"`
	Salary            string `json:"salary"`
	Status            string `json:"status"`
}

func (b contractBody) toInput() (contracts.Input, error) {
	in := contracts.Input{}
	ctype := b.PayType
	if ctype == "" {
		ctype = b.ContractType
	}
	in.ContractType = ctype
	in.Status = b.Status

	empStr := b.EmployeeID
	if empStr == "" {
		empStr = b.Employee
	}
	if empStr != "" {
		eid, err := uuid.Parse(empStr)
		if err != nil {
			return in, errBadEmployee
		}
		in.EmployeeID = eid
	}

	start := b.ContractStartDate
	if start == "" {
		start = b.StartDate
	}
	if start != "" {
		if d, err := parseDate(start); err == nil {
			in.StartDate = &d
		}
	}
	end := b.ContractEndDate
	if end == "" {
		end = b.EndDate
	}
	if end != "" {
		if d, err := parseDate(end); err == nil {
			in.EndDate = &d
		}
	}
	if b.Salary != "" {
		sal, err := parseDecimalDefault(b.Salary)
		if err != nil {
			return in, errBadSalary
		}
		in.Salary = sal
	}
	return in, nil
}

type contractError struct{ msg string }

func (e contractError) Error() string { return e.msg }

var (
	errBadEmployee = contractError{"invalid employee id"}
	errBadSalary   = contractError{"invalid salary (must be a decimal string)"}
)

func (h *ContractsHandler) List(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	if empID == nil {
		empID = optionalUUIDParam(r, "employee")
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.List(r.Context(), scope.TenantID, empID, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list contracts")
		return
	}
	out := make([]contractView, 0, len(rows))
	for _, c := range rows {
		out = append(out, h.view(r.Context(), scope.TenantID, c))
	}
	writePaginated(w, out, total, p)
}

func (h *ContractsHandler) Get(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	c, err := h.svc.Get(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "contract not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch contract")
		return
	}
	writeJSON(w, http.StatusOK, h.view(r.Context(), scope.TenantID, c))
}

func (h *ContractsHandler) Create(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	var body contractBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := body.toInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	if in.EmployeeID == uuid.Nil {
		writeError(w, http.StatusBadRequest, "bad_request", "employee is required")
		return
	}
	c, err := h.svc.Create(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, h.view(r.Context(), scope.TenantID, c))
}

func (h *ContractsHandler) Update(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body contractBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := body.toInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	c, err := h.svc.Update(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "contract not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, h.view(r.Context(), scope.TenantID, c))
}

func (h *ContractsHandler) Delete(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.Delete(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
