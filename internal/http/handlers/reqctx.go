package handlers

import (
	"context"
	"net/http"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/google/uuid"

	mw "github.com/Bengo-Hub/erp-api/internal/http/middleware"
	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
)

// rbacService is the package-level erp RBAC service used by requirePermission to consult
// locally-assigned service permissions (Trinity Layer 3). Set once at startup via
// SetRBACService so the 60+ requirePermission call sites need no signature change.
var rbacService *rbac.Service

// SetRBACService wires the erp RBAC service for local permission enforcement. Call once
// from main.go before mounting routes.
func SetRBACService(svc *rbac.Service) { rbacService = svc }

// employeeResolver resolves a caller's OWN employee id from their SSO subject, for ESS
// self-scoping (?mine=true). Set once at startup via SetEmployeeResolver.
type employeeResolver func(ctx context.Context, tenantID uuid.UUID, externalID string) (uuid.UUID, bool)

var resolveSelfEmployee employeeResolver

// SetEmployeeResolver wires the self-employee resolver (employees.Service.EmployeeIDForExternalUser).
func SetEmployeeResolver(f employeeResolver) { resolveSelfEmployee = f }

// selfOrParamEmployeeID returns the caller's OWN employee id when ?mine=true (ESS), else
// the employee_id query param. When mine=true but the caller has no employee record, it
// returns uuid.Nil so the query matches nothing (an employee never sees others' data).
func selfOrParamEmployeeID(r *http.Request, scope RequestScope) *uuid.UUID {
	if r.URL.Query().Get("mine") == "true" {
		if resolveSelfEmployee != nil && scope.Claims != nil {
			ctx := scope.Ctx
			if ctx == nil {
				ctx = context.Background()
			}
			if id, ok := resolveSelfEmployee(ctx, scope.TenantID, scope.Claims.Subject); ok {
				return &id
			}
		}
		nilID := uuid.Nil
		return &nilID
	}
	return optionalUUIDParam(r, "employee_id")
}

// RequestScope is the resolved tenant/outlet/identity for an authenticated request.
// Every HRM handler derives one and filters all queries by TenantID.
type RequestScope struct {
	Claims   *authclient.Claims
	TenantID uuid.UUID
	UserID   uuid.UUID
	// OutletID is the resolved outlet (uuid.Nil = all-outlets/HQ). For restricted users
	// this is forced to their JWT outlet by OutletContext middleware.
	OutletID uuid.UUID
	// Ctx carries the request context so requirePermission can query local erp permissions
	// without a signature change across every call site.
	Ctx context.Context
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
	tenantID := *tenantPtr
	// Platform-owner drill-in: a platform owner may scope the request to another tenant
	// via ?tenantId= (or X-Tenant-ID). STRICTLY gated on IsPlatformOwner so a regular
	// tenant user cannot spoof the header to reach another tenant's data.
	if claims.IsPlatformOwner {
		if ov := platformTenantOverride(r); ov != uuid.Nil {
			tenantID = ov
		}
	}
	scope := RequestScope{Claims: claims, TenantID: tenantID, Ctx: r.Context()}
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

// platformTenantOverride reads a platform owner's drilled-into tenant from the
// ?tenantId=/?tenant_id= query param or the X-Tenant-ID header. Returns uuid.Nil if
// absent/invalid. Callers MUST gate this on claims.IsPlatformOwner.
func platformTenantOverride(r *http.Request) uuid.UUID {
	for _, v := range []string{
		r.URL.Query().Get("tenantId"),
		r.URL.Query().Get("tenant_id"),
		r.Header.Get("X-Tenant-ID"),
	} {
		if v == "" {
			continue
		}
		if id, err := uuid.Parse(v); err == nil && id != uuid.Nil {
			return id
		}
	}
	return uuid.Nil
}

// requirePermission gates a handler on an RBAC permission code. Platform owners and
// superusers bypass. Returns false (and writes 403) when not permitted.
func requirePermission(w http.ResponseWriter, scope RequestScope, perm string) bool {
	if scope.Claims == nil {
		writeError(w, http.StatusForbidden, "forbidden", "no claims")
		return false
	}
	if hasPermission(scope, perm) {
		return true
	}
	writeError(w, http.StatusForbidden, "forbidden", "missing permission: "+perm)
	return false
}

// hasPermission is requirePermission's rule without the 403, for optional capabilities (for
// example approving a claim over budget).
func hasPermission(scope RequestScope, perm string) bool {
	c := scope.Claims
	if c == nil {
		return false
	}
	if c.IsPlatformOwner || c.IsSuperuser() || c.IsService || c.HasPermission(perm) {
		return true
	}
	// Fall back to locally-assigned erp service permissions (Trinity Layer 3): a global SSO
	// role mapped to an erp role grants perms that aren't carried in the JWT permission claim.
	if rbacService != nil && scope.UserID != uuid.Nil {
		ctx := scope.Ctx
		if ctx == nil {
			ctx = context.Background()
		}
		if perms, err := rbacService.GetUserPermissions(ctx, scope.TenantID, scope.UserID); err == nil {
			for _, p := range perms {
				if p.PermissionCode == perm {
					return true
				}
			}
		}
	}
	return false
}
