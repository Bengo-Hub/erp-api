package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
)

type allocationBody struct {
	EmployeeID        string   `json:"employee_id"`
	ProjectID         string   `json:"project_id"`
	ProjectName       string   `json:"project_name"`
	CostCenterID      string   `json:"cost_center_id"`
	AllocationPercent string   `json:"allocation_percent"`
	FixedAmount       *float64 `json:"fixed_amount"`
}

func (b allocationBody) toInput() employees.AllocationInput {
	in := employees.AllocationInput{ProjectName: b.ProjectName, FixedAmount: b.FixedAmount}
	if id, err := uuid.Parse(b.EmployeeID); err == nil {
		in.EmployeeID = id
	}
	if id, err := uuid.Parse(b.ProjectID); err == nil {
		in.ProjectID = id
	}
	if id, err := uuid.Parse(b.CostCenterID); err == nil {
		in.CostCenterID = &id
	}
	if b.AllocationPercent != "" {
		if p, err := decimal.NewFromString(b.AllocationPercent); err == nil {
			in.AllocationPercent = p
		}
	}
	return in
}

func allocationView(a *ent.EmployeeProjectAllocation) map[string]any {
	v := map[string]any{
		"id": a.ID, "employee_id": a.EmployeeID, "project_id": a.ProjectID,
		"project_name": a.ProjectName, "allocation_percent": a.AllocationPercent.String(),
		"is_active": a.IsActive, "created_at": a.CreatedAt,
	}
	if a.CostCenterID != nil {
		v["cost_center_id"] = a.CostCenterID
	}
	if a.FixedAmount != nil {
		v["fixed_amount"] = *a.FixedAmount
	}
	return v
}

func (h *EmployeesHandler) ListAllocations(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	var empID, projID *uuid.UUID
	if v := r.URL.Query().Get("employee_id"); v != "" {
		if id, err := uuid.Parse(v); err == nil {
			empID = &id
		}
	}
	if v := r.URL.Query().Get("project_id"); v != "" {
		if id, err := uuid.Parse(v); err == nil {
			projID = &id
		}
	}
	rows, err := h.svc.ListAllocations(r.Context(), scope.TenantID, empID, projID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list allocations")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, a := range rows {
		out = append(out, allocationView(a))
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": out, "count": len(out)})
}

func (h *EmployeesHandler) CreateAllocation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	var body allocationBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	a, err := h.svc.CreateAllocation(r.Context(), scope.TenantID, body.toInput())
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, allocationView(a))
}

func (h *EmployeesHandler) UpdateAllocation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body allocationBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	a, err := h.svc.UpdateAllocation(r.Context(), scope.TenantID, id, body.toInput())
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, allocationView(a))
}

func (h *EmployeesHandler) DeleteAllocation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteAllocation(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "deleted"})
}
