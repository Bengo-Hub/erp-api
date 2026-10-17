package rbac

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/customuser"
	"github.com/Bengo-Hub/erp-api/internal/ent/permission"
	"github.com/Bengo-Hub/erp-api/internal/ent/role"
	"github.com/Bengo-Hub/erp-api/internal/ent/userroleassignment"
)

// Service provides erp-api service-RBAC operations: JIT user provisioning, role
// reconciliation on every login (add + remove), and resolution
// of roles/permissions for GET /auth/me.
type Service struct {
	orm *ent.Client
	log *zap.Logger
}

func NewService(orm *ent.Client, log *zap.Logger) *Service {
	return &Service{orm: orm, log: log.Named("rbac.Service")}
}

// EnsureUserFromToken JIT-provisions the local CustomUser shadow keyed on external_id
// (= JWT sub) and reconciles their service-role assignments to exactly match the
// claim roles. Idempotent; safe to call on every authenticated request.
func (s *Service) EnsureUserFromToken(ctx context.Context, tenantID uuid.UUID, externalID, email string, claimRoles ...string) (*ent.CustomUser, error) {
	if s == nil || s.orm == nil {
		return nil, fmt.Errorf("rbac: service not initialised")
	}
	externalID = strings.TrimSpace(externalID)
	if externalID == "" {
		return nil, fmt.Errorf("rbac: empty external_id")
	}

	u, err := s.orm.CustomUser.Query().
		Where(customuser.ExternalID(externalID)).
		Only(ctx)
	switch {
	case ent.IsNotFound(err):
		create := s.orm.CustomUser.Create().
			SetTenantID(tenantID).
			SetExternalID(externalID).
			SetEmail(email)
		// Pin the primary key to the external_id (JWT sub) itself, NOT ent's random
		// UUID default. scope.UserID (reqctx.go, = claims.UserID() = the JWT sub) is
		// used platform-wide as the canonical actor id — RBAC's UserRoleAssignment.UserID,
		// tasks/approvals/leave/appraisals "created_by"/"approved_by", etc. all key off it.
		// Letting CustomUser.ID default to a fresh random UUID silently detached the local
		// RBAC assignment (keyed on that random id) from every lookup keyed on scope.UserID,
		// so requirePermission's rbacService fallback never found the role it had just
		// granted — a full-tenant, every-non-superuser 403 that no amount of role/permission
		// seeding could fix. (Found via prod audit 2026-07-10: 65/65 CustomUser rows had
		// id != external_id.)
		if extUUID, perr := uuid.Parse(externalID); perr == nil {
			create = create.SetID(extUUID)
		}
		u, err = create.Save(ctx)
		if err != nil {
			return nil, fmt.Errorf("rbac: create user: %w", err)
		}
	case err != nil:
		return nil, fmt.Errorf("rbac: query user: %w", err)
	default:
		upd := u.Update()
		if email != "" && email != u.Email {
			upd = upd.SetEmail(email)
		}
		if u.TenantID == uuid.Nil && tenantID != uuid.Nil {
			upd = upd.SetTenantID(tenantID)
		}
		if u, err = upd.Save(ctx); err != nil {
			return nil, fmt.Errorf("rbac: update user: %w", err)
		}
	}

	if err := s.reconcileRoles(ctx, tenantID, u.ID, claimRoles); err != nil {
		// Non-fatal: a missing role mapping must not break the request.
		s.log.Warn("role reconciliation failed", zap.String("user", u.ID.String()), zap.Error(err))
	}
	return u, nil
}

// reconcileRoles makes the user's assignments exactly match claimRoles for this tenant:
// it adds assignments for newly-granted roles and removes assignments no longer present
// in the token. Roles absent from the local Role table are skipped (not auto-created).
func (s *Service) reconcileRoles(ctx context.Context, tenantID, userID uuid.UUID, claimRoles []string) error {
	desired := map[uuid.UUID]bool{}
	for _, code := range claimRoles {
		code = strings.TrimSpace(code)
		if code == "" {
			continue
		}
		r, err := s.resolveRole(ctx, tenantID, code)
		if err != nil || r == nil {
			continue
		}
		desired[r.ID] = true
	}

	existing, err := s.orm.UserRoleAssignment.Query().
		Where(
			userroleassignment.TenantID(tenantID),
			userroleassignment.UserID(userID),
		).All(ctx)
	if err != nil {
		return fmt.Errorf("query assignments: %w", err)
	}

	have := map[uuid.UUID]bool{}
	for _, a := range existing {
		have[a.RoleID] = true
		if !desired[a.RoleID] {
			if err := s.orm.UserRoleAssignment.DeleteOne(a).Exec(ctx); err != nil {
				return fmt.Errorf("remove stale assignment: %w", err)
			}
		}
	}

	for roleID := range desired {
		if have[roleID] {
			continue
		}
		if _, err := s.orm.UserRoleAssignment.Create().
			SetTenantID(tenantID).
			SetUserID(userID).
			SetRoleID(roleID).
			Save(ctx); err != nil {
			return fmt.Errorf("add assignment: %w", err)
		}
	}
	return nil
}

// resolveRole finds a role by code, preferring a tenant-specific role then falling
// back to a global (tenant_id IS NULL) system role.
func (s *Service) resolveRole(ctx context.Context, tenantID uuid.UUID, code string) (*ent.Role, error) {
	r, err := s.orm.Role.Query().
		Where(role.TenantID(tenantID), role.RoleCode(code)).
		Only(ctx)
	if err == nil {
		return r, nil
	}
	if !ent.IsNotFound(err) {
		return nil, err
	}
	r, err = s.orm.Role.Query().
		Where(role.TenantIDIsNil(), role.RoleCode(code)).
		First(ctx)
	if ent.IsNotFound(err) {
		return nil, nil
	}
	return r, err
}

// GetUserRoles returns the locally-assigned roles for a user within a tenant.
func (s *Service) GetUserRoles(ctx context.Context, tenantID, userID uuid.UUID) ([]*ent.Role, error) {
	assignments, err := s.orm.UserRoleAssignment.Query().
		Where(userroleassignment.TenantID(tenantID), userroleassignment.UserID(userID)).
		All(ctx)
	if err != nil {
		return nil, err
	}
	if len(assignments) == 0 {
		return nil, nil
	}
	ids := make([]uuid.UUID, 0, len(assignments))
	for _, a := range assignments {
		ids = append(ids, a.RoleID)
	}
	return s.orm.Role.Query().Where(role.IDIn(ids...)).All(ctx)
}

// GetUserPermissions returns the distinct permissions granted via the user's roles.
func (s *Service) GetUserPermissions(ctx context.Context, tenantID, userID uuid.UUID) ([]*ent.Permission, error) {
	roles, err := s.GetUserRoles(ctx, tenantID, userID)
	if err != nil {
		return nil, err
	}
	if len(roles) == 0 {
		return nil, nil
	}
	roleIDs := make([]uuid.UUID, 0, len(roles))
	for _, r := range roles {
		roleIDs = append(roleIDs, r.ID)
	}
	return s.orm.Permission.Query().
		Where(permission.HasRolesWith(role.IDIn(roleIDs...))).
		All(ctx)
}

// ── Service-level RBAC management (erp owns its roles/permissions) ──────────────

// ErrSystemRole is returned when a mutation targets a protected system role.
var ErrSystemRole = fmt.Errorf("system roles cannot be modified or deleted")

// ErrWildcardRole is returned when editing the permissions of the all-access role.
var ErrWildcardRole = fmt.Errorf("the all-access role's permissions are not editable")

// wildcardRoleCode is the erp all-access role whose permissions must not be edited.
const wildcardRoleCode = "erp_admin"

// RoleWithCounts is a role plus its permission + assigned-member counts (for the UI list).
type RoleWithCounts struct {
	Role            *ent.Role
	PermissionCount int
	MemberCount     int
}

// ListRoles returns global (tenant_id IS NULL) + tenant-specific roles with counts.
func (s *Service) ListRoles(ctx context.Context, tenantID uuid.UUID) ([]RoleWithCounts, error) {
	rows, err := s.orm.Role.Query().
		Where(role.Or(role.TenantIDIsNil(), role.TenantID(tenantID))).
		Order(ent.Asc(role.FieldRoleCode)).
		All(ctx)
	if err != nil {
		return nil, err
	}
	out := make([]RoleWithCounts, 0, len(rows))
	for _, r := range rows {
		pc, _ := r.QueryPermissions().Count(ctx)
		mc, _ := s.orm.UserRoleAssignment.Query().
			Where(userroleassignment.TenantID(tenantID), userroleassignment.RoleID(r.ID)).
			Count(ctx)
		out = append(out, RoleWithCounts{Role: r, PermissionCount: pc, MemberCount: mc})
	}
	return out, nil
}

// ListPermissions returns the full erp permission catalogue.
func (s *Service) ListPermissions(ctx context.Context) ([]*ent.Permission, error) {
	return s.orm.Permission.Query().Order(ent.Asc(permission.FieldPermissionCode)).All(ctx)
}

// GetRole returns a role (scoped to tenant or global) and its permission codes.
func (s *Service) GetRole(ctx context.Context, tenantID, roleID uuid.UUID) (*ent.Role, []string, error) {
	r, err := s.orm.Role.Query().
		Where(role.ID(roleID), role.Or(role.TenantIDIsNil(), role.TenantID(tenantID))).
		Only(ctx)
	if err != nil {
		return nil, nil, err
	}
	perms, err := r.QueryPermissions().Order(ent.Asc(permission.FieldPermissionCode)).All(ctx)
	if err != nil {
		return nil, nil, err
	}
	codes := make([]string, 0, len(perms))
	for _, p := range perms {
		codes = append(codes, p.PermissionCode)
	}
	return r, codes, nil
}

// CreateRole creates a tenant-scoped custom (non-system) role.
func (s *Service) CreateRole(ctx context.Context, tenantID uuid.UUID, code, name, description string) (*ent.Role, error) {
	code = strings.TrimSpace(code)
	name = strings.TrimSpace(name)
	if code == "" || name == "" {
		return nil, fmt.Errorf("role_code and name are required")
	}
	return s.orm.Role.Create().
		SetTenantID(tenantID).
		SetRoleCode(code).
		SetName(name).
		SetDescription(description).
		SetIsSystemRole(false).
		Save(ctx)
}

// UpdateRole edits a non-system role's name/description.
func (s *Service) UpdateRole(ctx context.Context, tenantID, roleID uuid.UUID, name, description string) (*ent.Role, error) {
	r, err := s.orm.Role.Get(ctx, roleID)
	if err != nil {
		return nil, err
	}
	if r.IsSystemRole {
		return nil, ErrSystemRole
	}
	upd := r.Update()
	if strings.TrimSpace(name) != "" {
		upd = upd.SetName(strings.TrimSpace(name))
	}
	upd = upd.SetDescription(description)
	return upd.Save(ctx)
}

// DeleteRole removes a non-system role and its permission + user assignments.
func (s *Service) DeleteRole(ctx context.Context, roleID uuid.UUID) error {
	r, err := s.orm.Role.Get(ctx, roleID)
	if err != nil {
		return err
	}
	if r.IsSystemRole {
		return ErrSystemRole
	}
	if _, err := s.orm.UserRoleAssignment.Delete().Where(userroleassignment.RoleID(roleID)).Exec(ctx); err != nil {
		return fmt.Errorf("clear assignments: %w", err)
	}
	// Clearing the M2M edge removes the join rows; then delete the role.
	if err := r.Update().ClearPermissions().Exec(ctx); err != nil {
		return fmt.Errorf("clear permissions: %w", err)
	}
	return s.orm.Role.DeleteOne(r).Exec(ctx)
}

// SetRolePermissions reconciles a role's permissions to exactly the given codes.
// The all-access role (erp_admin) is protected. Unknown codes are skipped.
func (s *Service) SetRolePermissions(ctx context.Context, roleID uuid.UUID, codes []string) error {
	r, err := s.orm.Role.Get(ctx, roleID)
	if err != nil {
		return err
	}
	if r.RoleCode == wildcardRoleCode {
		return ErrWildcardRole
	}
	perms, err := s.orm.Permission.Query().Where(permission.PermissionCodeIn(codes...)).All(ctx)
	if err != nil {
		return fmt.Errorf("resolve permissions: %w", err)
	}
	ids := make([]uuid.UUID, 0, len(perms))
	for _, p := range perms {
		ids = append(ids, p.ID)
	}
	return r.Update().ClearPermissions().AddPermissionIDs(ids...).Exec(ctx)
}

// AssignUserRole idempotently grants a service role to a user within a tenant.
func (s *Service) AssignUserRole(ctx context.Context, tenantID, userID, roleID uuid.UUID) error {
	exists, err := s.orm.UserRoleAssignment.Query().
		Where(userroleassignment.TenantID(tenantID), userroleassignment.UserID(userID), userroleassignment.RoleID(roleID)).
		Exist(ctx)
	if err != nil {
		return err
	}
	if exists {
		return nil
	}
	_, err = s.orm.UserRoleAssignment.Create().
		SetTenantID(tenantID).SetUserID(userID).SetRoleID(roleID).Save(ctx)
	return err
}

// RemoveUserRole revokes a service role from a user within a tenant.
func (s *Service) RemoveUserRole(ctx context.Context, tenantID, userID, roleID uuid.UUID) error {
	_, err := s.orm.UserRoleAssignment.Delete().
		Where(userroleassignment.TenantID(tenantID), userroleassignment.UserID(userID), userroleassignment.RoleID(roleID)).
		Exec(ctx)
	return err
}
