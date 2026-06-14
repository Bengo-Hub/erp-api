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
// reconciliation on every login (add + remove — fixes gaps §1.5), and resolution
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
		u, err = s.orm.CustomUser.Create().
			SetTenantID(tenantID).
			SetExternalID(externalID).
			SetEmail(email).
			Save(ctx)
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
