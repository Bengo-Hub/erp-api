package handlers

import (
	"net/http"
	"strings"
	"time"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// ProjectHours godoc
// @Summary Hours logged per project
// @Description Approved and submitted timesheet hours (regular plus overtime) per project, for project utilisation and earned value. ?project_ids=a,b (max 100) &from=&to= (YYYY-MM-DD, inclusive). projects-api calls it S2S with X-API-Key and X-Tenant-ID.
// @Tags attendance
// @Produce json
// @Success 200 {object} map[string][]attendance.ProjectHours
// @Router /hrm/attendance/timesheets/project-hours [get]
func (h *AttendanceHandler) ProjectHours(w http.ResponseWriter, r *http.Request) {
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
	var ids []uuid.UUID
	for _, raw := range strings.Split(q.Get("project_ids"), ",") {
		if raw = strings.TrimSpace(raw); raw == "" {
			continue
		}
		id, err := uuid.Parse(raw)
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "project_ids must be UUIDs")
			return
		}
		ids = append(ids, id)
	}
	if len(ids) > attendance.MaxProjectHoursBatch {
		writeError(w, http.StatusBadRequest, "bad_request", "at most 100 project_ids")
		return
	}
	var from, to time.Time
	for key, dst := range map[string]*time.Time{"from": &from, "to": &to} {
		if v := q.Get(key); v != "" {
			d, err := time.Parse(time.DateOnly, v)
			if err != nil {
				writeError(w, http.StatusBadRequest, "bad_request", key+" must be YYYY-MM-DD")
				return
			}
			*dst = d
		}
	}
	rows, err := h.svc.ProjectHours(r.Context(), tenantID, ids, from, to)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to sum project hours")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}
