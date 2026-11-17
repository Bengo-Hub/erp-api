package handlers

import (
	"errors"
	"net/http"
	"strings"
	"time"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// Capacity godoc
// @Summary Working hours per person and ISO week
// @Description Each auth user's capacity per ISO week from the Monday of from to the week holding to (whole weeks): the weekly hours of the employee's standard work shift minus approved leave and public holidays (national, plus the county of the employee's HR region or its parent). Each week also reports pending_leave_hours (leave awaiting approval), which is not taken off. ?auth_user_ids=a,b (at most 500) &from=&to= (YYYY-MM-DD, at most 366 days apart). has_employee is false for a user ERP has no live employee for; configured is false when that employee has no work shift with hours, and then weekly_hours is 0 and weeks is empty. projects-api calls it S2S with X-API-Key and X-Tenant-ID for its workload.
// @Tags attendance
// @Produce json
// @Success 200 {object} map[string][]attendance.PersonCapacity
// @Router /hrm/attendance/capacity [get]
func (h *AttendanceHandler) Capacity(w http.ResponseWriter, r *http.Request) {
	var tenantID uuid.UUID
	if claims, ok := authclient.ClaimsFromContext(r.Context()); ok && claims != nil && claims.IsService {
		id, ok := resolveTenant(w, r)
		if !ok {
			return
		}
		tenantID = id
	} else {
		scope, ok := scopeFromRequest(w, r)
		if !ok || !requirePermission(w, scope, permAttendanceView) {
			return
		}
		tenantID = scope.TenantID
	}
	q := r.URL.Query()
	var ids []string
	seen := map[string]bool{}
	for _, raw := range strings.Split(q.Get("auth_user_ids"), ",") {
		if raw = strings.ToLower(strings.TrimSpace(raw)); raw == "" || seen[raw] {
			continue
		}
		if _, err := uuid.Parse(raw); err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "auth_user_ids must be UUIDs")
			return
		}
		seen[raw] = true
		ids = append(ids, raw)
	}
	if len(ids) > attendance.MaxCapacityUsers {
		writeError(w, http.StatusBadRequest, "bad_request", "at most 500 auth_user_ids")
		return
	}
	from, err1 := time.Parse(time.DateOnly, q.Get("from"))
	to, err2 := time.Parse(time.DateOnly, q.Get("to"))
	if err1 != nil || err2 != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "from and to are required as YYYY-MM-DD")
		return
	}
	rows, err := h.svc.Capacity(r.Context(), tenantID, ids, from, to)
	if errors.Is(err, attendance.ErrCapacityRange) {
		writeError(w, http.StatusBadRequest, "bad_request", "to must be on or after from and at most 366 days later")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to read capacity")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}
