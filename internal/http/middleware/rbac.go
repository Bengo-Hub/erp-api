package middleware

import (
	"net/http"
	"strings"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
)

// EnsureServiceUser JIT-provisions the local erp CustomUser shadow and reconciles their
// erp service-role assignments from the SSO claim roles on every authenticated request
// (Trinity Layer 3 sync). It must run after RequireAuth (claims present) and is non-fatal:
// a provisioning error never blocks the request — the JWT remains the source of truth and
// platform owners/superusers bypass local RBAC anyway.
func EnsureServiceUser(svc *rbac.Service, log *zap.Logger) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			ctx := r.Context()
			claims, ok := authclient.ClaimsFromContext(ctx)
			if ok && claims != nil && svc != nil && !claims.IsService && claims.Subject != "" {
				if tenantPtr, err := claims.TenantUUID(); err == nil && tenantPtr != nil && *tenantPtr != uuid.Nil {
					mapped := MapGlobalRolesToERP(claims.Roles)
					if _, err := svc.EnsureUserFromToken(ctx, *tenantPtr, claims.Subject, claims.Email, mapped...); err != nil && log != nil {
						log.Debug("rbac JIT provisioning failed (non-fatal)", zap.Error(err))
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
