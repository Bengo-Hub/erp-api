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
			if ok && claims != nil && !claims.IsService && claims.Subject != "" {
				if tenantPtr, err := claims.TenantUUID(); err == nil && tenantPtr != nil && *tenantPtr != uuid.Nil {
					if svc != nil {
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

// erpKnownRoles are the SSO global role names that map 1:1 onto an erp system role
// (mirrors the roleGrants keys in cmd/seed/main.go — kept as a literal set here since
// cmd/seed is package main and can't be imported). Anything NOT in this set is a role
// from another domain entirely (POS/logistics/hospitality/etc. — cashier, rider, driver,
// waiter, stylist, technician, generic "manager", ...) with no HRM relevance, so it falls
// back to "staff": every tenant employee, regardless of their business-specific role in
// other services, still gets basic ESS access in ERP (own payslips, leave, attendance).
var erpKnownRoles = map[string]bool{
	"erp_admin":           true,
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

// MapGlobalRolesToERP maps SSO global role names to erp service-role codes. The platform
// all-access roles (superuser/admin and the legacy Django "superusers" group) are mapped to
// erp_admin; names that match a known erp role (erpKnownRoles) pass through unchanged;
// every other name (a role scoped to a different service — POS, logistics, hospitality,
// etc. — with no HRM relevance) defaults to "staff" so that user still gets ESS access
// (own payslips/leave/attendance) instead of zero erp permissions.
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
		case lower == "superuser" || lower == "admin" || lower == "superusers":
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
