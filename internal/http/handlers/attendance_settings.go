package handlers

import (
	"encoding/json"
	"io"
	"net/http"

	"github.com/go-chi/chi/v5"
)

// registerSettingsRoutes mounts the tenant attendance settings (thresholds, geo mode,
// auto-absent switch) under /hrm/attendance.
func (h *AttendanceHandler) registerSettingsRoutes(ar chi.Router) {
	ar.Get("/settings", h.GetSettings)
	ar.Put("/settings", h.UpdateSettings)
}

// GetSettings returns the tenant's attendance settings (defaults until saved).
func (h *AttendanceHandler) GetSettings(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	st, err := h.svc.GetSettings(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load attendance settings")
		return
	}
	writeJSON(w, http.StatusOK, st)
}

// UpdateSettings applies a partial update; keys left out keep their current value.
func (h *AttendanceHandler) UpdateSettings(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	raw, err := io.ReadAll(io.LimitReader(r.Body, 64<<10))
	if err != nil || !json.Valid(raw) {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	st, err := h.svc.SaveSettings(r.Context(), scope.TenantID, raw)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_settings", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, st)
}
