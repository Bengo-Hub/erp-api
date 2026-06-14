package handlers

import (
	"net/http"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/google/uuid"

	mw "github.com/Bengo-Hub/erp-api/internal/http/middleware"
)

// RequestScope is the resolved tenant/outlet/identity for an authenticated request.
// Every HRM handler derives one and filters all queries by TenantID (gaps §2 isolation).
type RequestScope struct {
	Claims   *authclient.Claims
	TenantID uuid.UUID
	UserID   uuid.UUID
	// OutletID is the resolved outlet (uuid.Nil = all-outlets/HQ). For restricted users
	// this is forced to their JWT outlet by OutletContext middleware.
	OutletID uuid.UUID
}

// scopeFromRequest resolves the tenant scope or writes a 401/400 and returns ok=false.
// It enforces that a tenant id is present — no handler may run without tenant isolation.
func scopeFromRequest(w http.ResponseWriter, r *http.Request) (RequestScope, bool) {
	claims, ok := authclient.ClaimsFromContext(r.Context())
	if !ok || claims == nil {
		writeError(w, http.StatusUnauthorized, "unauthorized", "missing claims")
		return RequestScope{}, false
	}
	tenantPtr, err := claims.TenantUUID()
	if err != nil || tenantPtr == nil || *tenantPtr == uuid.Nil {
		writeError(w, http.StatusUnauthorized, "unauthorized", "missing or invalid tenant in token")
		return RequestScope{}, false
	}
	scope := RequestScope{Claims: claims, TenantID: *tenantPtr}
	if uid, uerr := claims.UserID(); uerr == nil {
		scope.UserID = uid
	}
	if oid := mw.GetOutletID(r.Context()); oid != "" {
		if parsed, perr := uuid.Parse(oid); perr == nil {
			scope.OutletID = parsed
		}
	}
	return scope, true
}

// requirePermission gates a handler on an RBAC permission code. Platform owners and
// superusers bypass. Returns false (and writes 403) when not permitted.
func requirePermission(w http.ResponseWriter, scope RequestScope, perm string) bool {
	c := scope.Claims
	if c == nil {
		writeError(w, http.StatusForbidden, "forbidden", "no claims")
		return false
	}
	if c.IsPlatformOwner || c.IsSuperuser() || c.IsService || c.HasPermission(perm) {
		return true
	}
	writeError(w, http.StatusForbidden, "forbidden", "missing permission: "+perm)
	return false
}
