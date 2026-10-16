package handlers

import (
	"net/http"
	"strconv"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

// Lookup lists active employees for a picker in another service (GET /hrm/employees/lookup?q=&limit=):
// id, staff number, name and email only. Other services call it S2S with X-API-Key and
// X-Tenant-ID (maskani-api's staff picker for work orders); a signed-in user needs employee view
// and sees their own tenant. The calling service decides whether the tenant's plan includes ERP
// before it calls.
func (h *EmployeesHandler) Lookup(w http.ResponseWriter, r *http.Request) {
	claims, ok := authclient.ClaimsFromContext(r.Context())
	if !ok || claims == nil {
		writeError(w, http.StatusUnauthorized, "unauthorized", "missing claims")
		return
	}
	var tenantID uuid.UUID
	if claims.IsService {
		if tenantID, ok = resolveTenant(w, r); !ok {
			return
		}
	} else {
		scope, ok := scopeFromRequest(w, r)
		if !ok || !requirePermission(w, scope, permEmployeeView) {
			return
		}
		tenantID = scope.TenantID
	}
	limit, _ := strconv.Atoi(r.URL.Query().Get("limit"))
	rows, err := h.svc.Lookup(r.Context(), tenantID, r.URL.Query().Get("q"), limit)
	if err != nil {
		h.log.Error("lookup employees", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to look up employees")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}
