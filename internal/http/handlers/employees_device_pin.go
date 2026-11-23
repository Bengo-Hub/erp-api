package handlers

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// WithAttendance enables the employee device PIN route.
func (h *EmployeesHandler) WithAttendance(svc *attendance.Service) *EmployeesHandler {
	h.attendance = svc
	return h
}

type devicePINBody struct {
	PIN string `json:"pin"`
}

// SetDevicePIN sets or clears (empty pin) the employee's biometric device PIN, unique per
// tenant. PUT /hrm/employees/{id}/device-pin.
func (h *EmployeesHandler) SetDevicePIN(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	if h.attendance == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "attendance is not configured")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b devicePINBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	emp, err := h.attendance.SetDevicePIN(r.Context(), scope.TenantID, id, b.PIN)
	switch {
	case errors.Is(err, attendance.ErrEmployeeNotFound):
		writeError(w, http.StatusNotFound, "not_found", "employee not found")
	case errors.Is(err, attendance.ErrPINTaken):
		writeError(w, http.StatusConflict, "pin_taken", err.Error())
	case err != nil && emp == nil:
		writeError(w, http.StatusBadRequest, "invalid_pin", err.Error())
	default:
		if err != nil {
			h.log.Warn("device pin saved but unmatched punches not attached", zap.Error(err))
		}
		writeJSON(w, http.StatusOK, map[string]any{"employee_id": emp.ID, "device_pin": emp.DevicePin})
	}
}
