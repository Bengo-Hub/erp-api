package middleware

import (
	"net/http"
	"strings"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
	"github.com/Bengo-Hub/erp-api/internal/services/usersync"
)

// EnsureServiceUser JIT-provisions the local erp CustomUser shadow and reconciles their
// erp service-role assignments from the SSO claim roles on every authenticated request
// (Trinity Layer 3 sync). It ALSO JIT-projects the AuthTenant shadow from the JWT's
// tenant_slug — so a tenant that predates the auth.tenant.* NATS consumer (and was therefore
// never projected) self-heals on the next authenticated request. This is what the public
// careers portal (TenantBySlug) relies on; without it, only event-projected tenants resolve.
// It must run after RequireAuth (claims present) and is non-fatal: a provisioning error never
// blocks the request — the JWT remains the source of truth.
func EnsureServiceUser(svc *rbac.Service, syncer *usersync.TenantSyncer, log *zap.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ctx := r.Context()
			claims, ok := authclient.ClaimsFromContext(ctx)
			// A tenant whose plan has no erp entitlement is not provisioned (no CustomUser, no tenant
			// shadow); the module gate that follows answers 403. Exempt tokens always pass.
			if ok && claims != nil && !claims.IsService && claims.Subject != "" && claims.HasServiceAccess("erp") {
				if tenantPtr, err := claims.TenantUUID(); err == nil && tenantPtr != nil && *tenantPtr != uuid.Nil {
					// The login shadow follows auth-api's member services (user_services claim): a member
					// without erp is not provisioned here. Employee records are not affected (every
					// staff member stays on the HR roster, user decision 2026-11-03).
					if svc != nil && claims.AllowsUserService("erp") {
						mapped := MapGlobalRolesToERP(claims.Roles)
						if _, err := svc.EnsureUserFromToken(ctx, *tenantPtr, claims.Subject, claims.Email, mapped...); err != nil && log != nil {
							log.Debug("rbac JIT provisioning failed (non-fatal)", zap.Error(err))
						}
					}
					// Self-healing tenant-shadow projection from the JWT slug (never clobbers a name
					// already set by the event consumer).
					if syncer != nil && claims.TenantSlug != "" {
						if err := syncer.EnsureTenantSlug(ctx, *tenantPtr, claims.TenantSlug); err != nil && log != nil {
							log.Debug("tenant shadow JIT projection failed (non-fatal)", zap.Error(err))
						}
					}
				}
			}
			next.ServeHTTP(w, r)
		})
	}
}

// adminRoleNames are the only SSO role names that make an ERP administrator. erp-ui's
// use-app-permissions.ts keeps the same list.
var adminRoleNames = map[string]bool{"admin": true, "superuser": true, "superusers": true, "erp_admin": true}

// erpKnownRoles are the SSO global role names that map 1:1 onto an erp system role (the built-in
// codes minus erp_admin). Anything in neither set is a role from another domain (POS, logistics,
// hospitality: cashier, rider, waiter, a generic "manager", ...) with no HRM relevance, so it falls
// back to "staff": every tenant employee still gets basic ESS access in ERP.
var erpKnownRoles = map[string]bool{
	"ceo":                 true,
	"cto":                 true,
	"ict_manager":         true,
	"ict_officer":         true,
	"hr_manager":          true,
	"hr_assistant":        true,
	"hr_viewer":           true,
	"payroll_manager":     true,
	"finance_manager":     true,
	"operations_manager":  true,
	"procurement_manager": true,
	"sales_manager":       true,
	"secretary":           true,
	"staff":               true,
}

// MapGlobalRolesToERP maps SSO global role names to erp service-role codes.
//
//   - exactly "admin", "superuser", "superusers" and "erp_admin" map to erp_admin. An admin of
//     another service (isp_admin, library_admin, hadia_admin, ...) is not an ERP administrator.
//   - names that match a known erp role (erpKnownRoles) pass through unchanged.
//   - every other name (a role scoped to a different service: POS, logistics, hospitality, ...)
//     defaults to "staff" so that user still gets ESS access (own payslips/leave/attendance).
func MapGlobalRolesToERP(globalRoles []string) []string {
	out := make([]string, 0, len(globalRoles)+1)
	addedAdmin := false
	addedStaff := false
	for _, role := range globalRoles {
		code := strings.TrimSpace(role)
		if code == "" {
			continue
		}
		lower := strings.ToLower(code)
		switch {
		case adminRoleNames[lower]:
			if !addedAdmin {
				out = append(out, "erp_admin")
				addedAdmin = true
			}
		case erpKnownRoles[lower]:
			out = append(out, lower)
		default:
			if !addedStaff {
				out = append(out, "staff")
				addedStaff = true
			}
		}
	}
	return out
}
