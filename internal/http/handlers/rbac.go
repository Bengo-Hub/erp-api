package handlers

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
)

// Service-level RBAC permission codes (erp owns its roles/permissions).
const (
	permRBACView   = "rbac.view"
	permRBACManage = "rbac.manage"
)

// RBACHandler serves /api/v1/rbac/* — erp's own service-level role/permission
// management (Trinity Layer 3). Global role assignment stays in auth-api.
type RBACHandler struct {
	log *zap.Logger
	svc *rbac.Service
}

func NewRBACHandler(log *zap.Logger, svc *rbac.Service) *RBACHandler {
	return &RBACHandler{log: log.Named("rbac.Handler"), svc: svc}
}

func (h *RBACHandler) RegisterRoutes(r chi.Router) {
	r.Route("/rbac", func(rr chi.Router) {
		rr.Get("/permissions", h.ListPermissions)
		rr.Get("/roles", h.ListRoles)
		rr.Post("/roles", h.CreateRole)
		rr.Get("/roles/{id}", h.GetRole)
		rr.Put("/roles/{id}", h.UpdateRole)
		rr.Delete("/roles/{id}", h.DeleteRole)
		rr.Put("/roles/{id}/permissions", h.SetRolePermissions)
		rr.Post("/users/{userId}/roles", h.AssignUserRole)
		rr.Delete("/users/{userId}/roles/{roleId}", h.RemoveUserRole)
	})
}

// isPlatformOwner reports whether the caller may change roles shared by every tenant.
func isPlatformOwner(scope RequestScope) bool {
	return scope.Claims != nil && scope.Claims.IsPlatformOwner
}

// actor is the caller of a role change, with what it may hand out.
func (h *RBACHandler) actor(r *http.Request, scope RequestScope) (rbac.Actor, error) {
	a := rbac.Actor{UserID: scope.UserID, PlatformOwner: isPlatformOwner(scope), Holds: func(code string) bool { return hasPermission(scope, code) }}
	if scope.Claims != nil {
		a.Subject = scope.Claims.Subject
		a.Admin = scope.Claims.IsSuperuser()
	}
	if !a.Admin && scope.UserID != uuid.Nil {
		admin, err := h.svc.HasAdminRole(r.Context(), scope.TenantID, scope.UserID)
		if err != nil {
			return a, err
		}
		a.Admin = admin
	}
	// The permission lookup queries the user's roles; keep the answers for the codes of one call.
	seen := map[string]bool{}
	holds := a.Holds
	a.Holds = func(code string) bool {
		v, ok := seen[code]
		if !ok {
			v = holds(code)
			seen[code] = v
		}
		return v
	}
	return a, nil
}

// writeRoleError answers a refused role change with a readable reason.
func writeRoleError(w http.ResponseWriter, code string, err error) {
	var beyond *rbac.BeyondGrantError
	switch {
	case errors.Is(err, rbac.ErrSystemRole):
		writeError(w, http.StatusForbidden, "system_role", err.Error())
	case errors.Is(err, rbac.ErrWildcardRole):
		writeError(w, http.StatusForbidden, "wildcard_role", err.Error())
	case errors.Is(err, rbac.ErrOwnRoles):
		writeError(w, http.StatusForbidden, "own_roles", err.Error())
	case errors.Is(err, rbac.ErrAdminOnlyRole), errors.As(err, &beyond):
		writeError(w, http.StatusForbidden, "beyond_own_permissions", err.Error())
	case errors.Is(err, rbac.ErrLastAdmin):
		writeError(w, http.StatusConflict, "last_admin", err.Error())
	case errors.Is(err, rbac.ErrBuiltInCode):
		writeError(w, http.StatusBadRequest, "built_in_code", err.Error())
	case errors.Is(err, rbac.ErrUserNotFound):
		writeError(w, http.StatusNotFound, "not_found", err.Error())
	case ent.IsNotFound(err):
		writeError(w, http.StatusNotFound, "not_found", "role not found")
	default:
		writeError(w, http.StatusBadRequest, code, err.Error())
	}
}

func roleView(r *ent.Role, permCount, memberCount int) map[string]any {
	var tenantID any
	if r.TenantID != nil {
		tenantID = r.TenantID.String()
	}
	return map[string]any{
		"id":               r.ID,
		"role_code":        r.RoleCode,
		"name":             r.Name,
		"description":      r.Description,
		"is_system_role":   r.IsSystemRole,
		"tenant_id":        tenantID,
		"permission_count": permCount,
		"member_count":     memberCount,
	}
}

func (h *RBACHandler) ListPermissions(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRBACView) {
		return
	}
	perms, err := h.svc.ListPermissions(r.Context())
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list permissions")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"permissions": perms})
}

func (h *RBACHandler) ListRoles(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRBACView) {
		return
	}
	rows, err := h.svc.ListRoles(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list roles")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, rc := range rows {
		out = append(out, roleView(rc.Role, rc.PermissionCount, rc.MemberCount))
	}
	writeJSON(w, http.StatusOK, map[string]any{"roles": out})
}

func (h *RBACHandler) GetRole(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRBACView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	role, codes, err := h.svc.GetRole(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "role not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load role")
		return
	}
	view := roleView(role, len(codes), 0)
	view["permission_codes"] = codes
	writeJSON(w, http.StatusOK, view)
}

type roleBody struct {
	RoleCode    string `json:"role_code"`
	Name        string `json:"name"`
	Description string `json:"description"`
}

func (h *RBACHandler) CreateRole(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRBACManage) {
		return
	}
	var b roleBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	role, err := h.svc.CreateRole(r.Context(), scope.TenantID, b.RoleCode, b.Name, b.Description)
	if err != nil {
		writeRoleError(w, "create_failed", err)
		return
	}
	writeJSON(w, http.StatusCreated, roleView(role, 0, 0))
}

func (h *RBACHandler) UpdateRole(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRBACManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b roleBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	role, err := h.svc.UpdateRole(r.Context(), scope.TenantID, id, b.Name, b.Description, isPlatformOwner(scope))
	if err != nil {
		writeRoleError(w, "update_failed", err)
		return
	}
	writeJSON(w, http.StatusOK, roleView(role, 0, 0))
}

func (h *RBACHandler) DeleteRole(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRBACManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	a, err := h.actor(r, scope)
	if err == nil {
		err = h.svc.DeleteRole(r.Context(), a, scope.TenantID, id)
	}
	if err != nil {
		writeRoleError(w, "delete_failed", err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

type setPermsBody struct {
	PermissionCodes []string `json:"permission_codes"`
}

func (h *RBACHandler) SetRolePermissions(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRBACManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b setPermsBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	a, err := h.actor(r, scope)
	if err == nil {
		err = h.svc.SetRolePermissions(r.Context(), a, scope.TenantID, id, b.PermissionCodes)
	}
	if err != nil {
		writeRoleError(w, "update_failed", err)
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"role_id": id, "permission_codes": b.PermissionCodes})
}

type assignRoleBody struct {
	RoleID string `json:"role_id"`
}

func (h *RBACHandler) AssignUserRole(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRBACManage) {
		return
	}
	userID, err := uuid.Parse(chi.URLParam(r, "userId"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid user id")
		return
	}
	var b assignRoleBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	roleID, err := uuid.Parse(b.RoleID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid role id")
		return
	}
	a, err := h.actor(r, scope)
	if err == nil {
		err = h.svc.AssignUserRole(r.Context(), a, scope.TenantID, userID, roleID)
	}
	if err != nil {
		writeRoleError(w, "assign_failed", err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"user_id": userID, "role_id": roleID})
}

func (h *RBACHandler) RemoveUserRole(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRBACManage) {
		return
	}
	userID, err := uuid.Parse(chi.URLParam(r, "userId"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid user id")
		return
	}
	roleID, err := uuid.Parse(chi.URLParam(r, "roleId"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid role id")
		return
	}
	a, err := h.actor(r, scope)
	if err == nil {
		err = h.svc.RemoveUserRole(r.Context(), a, scope.TenantID, userID, roleID)
	}
	if err != nil {
		writeRoleError(w, "remove_failed", err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
