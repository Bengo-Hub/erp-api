package handlers

import (
	"net/http"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
)

// AuthHandler implements GET /api/v1/auth/me/ (the Trinity two-step).
// Service roles = local Ent roles; permissions = bare-codename permissions, merged
// with the SSO claim roles/permissions for the frontend to gate UI.
type AuthHandler struct {
	log         *zap.Logger
	rbacService *rbac.Service
}

func NewAuthHandler(log *zap.Logger, rbacService *rbac.Service) *AuthHandler {
	return &AuthHandler{log: log.Named("auth.Handler"), rbacService: rbacService}
}

// MeResponse is the payload returned by GET /auth/me.
type MeResponse struct {
	ID              string   `json:"id"`
	Email           string   `json:"email"`
	TenantID        string   `json:"tenant_id"`
	TenantSlug      string   `json:"tenant_slug"`
	OutletID        string   `json:"outlet_id,omitempty"`
	Roles           []string `json:"roles"`
	Permissions     []string `json:"permissions"`
	IsPlatformOwner bool     `json:"is_platform_owner"`
	IsSuperUser     bool     `json:"is_superuser"`
}

// Me handles GET /auth/me. JWT is already validated by auth middleware; the user is
// JIT-provisioned by the router middleware.
func (h *AuthHandler) Me(w http.ResponseWriter, r *http.Request) {
	claims, ok := authclient.ClaimsFromContext(r.Context())
	if !ok || claims.Subject == "" {
		writeError(w, http.StatusUnauthorized, "unauthorized", "missing claims")
		return
	}

	userID, err := claims.UserID()
	if err != nil || userID == uuid.Nil {
		writeError(w, http.StatusUnauthorized, "unauthorized", "invalid user id in token")
		return
	}
	tenantID, err := claims.TenantUUID()
	if err != nil || tenantID == nil {
		writeError(w, http.StatusUnauthorized, "unauthorized", "invalid tenant id in token")
		return
	}

	roles := make([]string, len(claims.Roles))
	copy(roles, claims.Roles)
	permissions := make([]string, len(claims.Permissions))
	copy(permissions, claims.Permissions)

	if h.rbacService != nil {
		if svcRoles, rErr := h.rbacService.GetUserRoles(r.Context(), *tenantID, userID); rErr == nil {
			for _, sr := range svcRoles {
				roles = appendUniqueStr(roles, sr.RoleCode)
			}
		} else {
			h.log.Debug("auth/me: local roles lookup failed", zap.Error(rErr))
		}
		if svcPerms, pErr := h.rbacService.GetUserPermissions(r.Context(), *tenantID, userID); pErr == nil {
			for _, sp := range svcPerms {
				permissions = appendUniqueStr(permissions, sp.PermissionCode)
			}
		} else {
			h.log.Debug("auth/me: local permissions lookup failed", zap.Error(pErr))
		}
	}

	respondJSON(w, http.StatusOK, MeResponse{
		ID:              claims.Subject,
		Email:           claims.Email,
		TenantID:        claims.TenantID,
		TenantSlug:      claims.GetTenantSlug(),
		OutletID:        claims.GetOutletID(),
		Roles:           roles,
		Permissions:     permissions,
		IsPlatformOwner: claims.IsPlatformOwner,
		IsSuperUser:     claims.IsSuperuser(),
	})
}

// RegisterRoutes mounts auth routes (caller wraps with RequireAuth).
func (h *AuthHandler) RegisterRoutes(r chi.Router) {
	r.Get("/auth/me", h.Me)
	r.Get("/auth/me/", h.Me)
}
