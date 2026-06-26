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

// MapGlobalRolesToERP maps SSO global role names to erp service-role codes. The platform
// all-access roles (superuser/admin and the legacy Django "superusers" group) are mapped to
// erp_admin; every other name passes through unchanged. resolveRole skips names that have no
// matching erp Role, so passing through extra Django group names (finance_manager, etc.) is
// harmless and future-proof — defining the matching erp Role later activates the mapping.
func MapGlobalRolesToERP(globalRoles []string) []string {
	out := make([]string, 0, len(globalRoles)+1)
	addedAdmin := false
	for _, role := range globalRoles {
		code := strings.TrimSpace(role)
		if code == "" {
			continue
		}
		switch strings.ToLower(code) {
		case "superuser", "admin", "superusers":
			if !addedAdmin {
				out = append(out, "erp_admin")
				addedAdmin = true
			}
		default:
			out = append(out, code)
		}
	}
	return out
}
