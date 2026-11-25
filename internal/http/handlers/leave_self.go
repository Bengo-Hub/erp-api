package handlers

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
)

const ownLeaveMessage = "you cannot approve your own leave request"

// isOwnEmployee reports whether an employee record belongs to the caller.
func isOwnEmployee(r *http.Request, scope RequestScope, employeeID uuid.UUID) bool {
	if resolveSelfEmployee == nil || scope.Claims == nil {
		return false
	}
	id, ok := resolveSelfEmployee(r.Context(), scope.TenantID, scope.Claims.Subject)
	return ok && id == employeeID
}

// leaveFiler decides whose leave this is. An empty employee_id, or the caller's own, is
// self-service and needs no permission; anyone else needs hrm.leave.manage.
func leaveFiler(w http.ResponseWriter, r *http.Request, employeeID string) (RequestScope, uuid.UUID, bool) {
	if employeeID == "" {
		return selfEmployee(w, r)
	}
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return scope, uuid.Nil, false
	}
	id, err := uuid.Parse(employeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return scope, uuid.Nil, false
	}
	if !isOwnEmployee(r, scope, id) && !requirePermission(w, scope, permLeaveManage) {
		return scope, uuid.Nil, false
	}
	return scope, id, true
}

// leaveRequestError answers 404 for a missing row and a readable 400 otherwise.
func leaveRequestError(w http.ResponseWriter, code string, err error) {
	switch {
	case errors.Is(err, leave.ErrEmployeeNotFound), errors.Is(err, leave.ErrRequestNotFound):
		writeError(w, http.StatusNotFound, "not_found", err.Error())
	case errors.Is(err, leave.ErrNoCalendar):
		writeError(w, http.StatusServiceUnavailable, "unavailable", err.Error())
	default:
		writeError(w, http.StatusBadRequest, code, clientMessage(err))
	}
}

// PreviewRequest counts the days a request would take, without filing it.
func (h *LeaveHandler) PreviewRequest(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	scope, empID, ok := leaveFiler(w, r, q.Get("employee_id"))
	if !ok {
		return
	}
	catID, err := uuid.Parse(q.Get("category_id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid category_id")
		return
	}
	start, err := parseDate(q.Get("start_date"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid start_date")
		return
	}
	end, err := parseDate(q.Get("end_date"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid end_date")
		return
	}
	out, err := h.svc.PreviewRequest(r.Context(), scope.TenantID, empID, catID, start, end)
	if err != nil {
		leaveRequestError(w, "preview_failed", err)
		return
	}
	writeJSON(w, http.StatusOK, out)
}

type typeSettingBody struct {
	CountMode   string `json:"count_mode"`
	BalanceRule string `json:"balance_rule"`
}

// SetCountMode changes how a leave type's days are counted.
func (h *LeaveHandler) SetCountMode(w http.ResponseWriter, r *http.Request) {
	h.setTypeSetting(w, r, func(scope RequestScope, id uuid.UUID, b typeSettingBody) (*leave.CategoryView, error) {
		return h.svc.SetCountMode(r.Context(), scope.TenantID, id, b.CountMode)
	})
}

// SetBalanceRule changes whether a leave type refuses requests beyond the balance.
func (h *LeaveHandler) SetBalanceRule(w http.ResponseWriter, r *http.Request) {
	h.setTypeSetting(w, r, func(scope RequestScope, id uuid.UUID, b typeSettingBody) (*leave.CategoryView, error) {
		return h.svc.SetBalanceRule(r.Context(), scope.TenantID, id, b.BalanceRule)
	})
}

// DeleteEntitlement removes a person's own entitlement; their balance goes back to the leave
// type's default days.
func (h *LeaveHandler) DeleteEntitlement(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	err = h.svc.DeleteEntitlement(r.Context(), scope.TenantID, id)
	if errors.Is(err, leave.ErrEntitlementNotFound) {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	if err != nil {
		h.log.Error("delete entitlement", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to delete the entitlement")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *LeaveHandler) setTypeSetting(w http.ResponseWriter, r *http.Request, save func(RequestScope, uuid.UUID, typeSettingBody) (*leave.CategoryView, error)) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b typeSettingBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := save(scope, id, b)
	if errors.Is(err, leave.ErrUnknownCategory) {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", clientMessage(err))
		return
	}
	writeJSON(w, http.StatusOK, row)
}
