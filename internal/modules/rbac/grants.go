package rbac

import (
	"context"
	"errors"
	"fmt"
	"slices"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/customuser"
	"github.com/Bengo-Hub/erp-api/internal/ent/permission"
	"github.com/Bengo-Hub/erp-api/internal/ent/role"
	"github.com/Bengo-Hub/erp-api/internal/ent/userroleassignment"
)

// builtInRoleCodes are the roles every company shares. cmd/seed creates them (its test keeps the
// two lists equal) and SSO roles resolve to them, so a company's own role may not take one.
var builtInRoleCodes = []string{
	"erp_admin", "ceo", "cto", "ict_manager", "ict_officer", "hr_manager", "hr_assistant", "hr_viewer",
	"payroll_manager", "finance_manager", "operations_manager", "procurement_manager", "sales_manager",
	"secretary", "staff",
}

// BuiltInRoleCodes returns the built-in role codes.
func BuiltInRoleCodes() []string { return slices.Clone(builtInRoleCodes) }

// IsBuiltInRoleCode reports whether a code is a built-in one, ignoring case and outer spaces.
func IsBuiltInRoleCode(code string) bool {
	return slices.Contains(builtInRoleCodes, strings.ToLower(strings.TrimSpace(code)))
}

// refuseBuiltInCode refuses a custom role's code or name that equals the code of a shared role.
func (s *Service) refuseBuiltInCode(ctx context.Context, values ...string) error {
	for _, v := range values {
		v = strings.TrimSpace(v)
		if v == "" {
			continue
		}
		if IsBuiltInRoleCode(v) {
			return ErrBuiltInCode
		}
		taken, err := s.orm.Role.Query().Where(role.TenantIDIsNil(), role.RoleCodeEqualFold(v)).Exist(ctx)
		if err != nil {
			return fmt.Errorf("rbac: check role code: %w", err)
		}
		if taken {
			return ErrBuiltInCode
		}
	}
	return nil
}

// Readable refusals.
var (
	ErrBuiltInCode   = errors.New("this is the key of a built-in role; choose another one")
	ErrOwnRoles      = errors.New("you cannot change your own roles; ask another administrator")
	ErrLastAdmin     = errors.New("this is the last administrator of the company; give someone else the administrator role first")
	ErrAdminOnlyRole = errors.New("only an administrator can give the administrator role")
)

// BeyondGrantError refuses handing out permissions the caller does not hold.
type BeyondGrantError struct{ Codes []string }

func (e *BeyondGrantError) Error() string {
	shown := e.Codes
	more := ""
	if len(shown) > 5 {
		more = fmt.Sprintf(" and %d more", len(shown)-5)
		shown = shown[:5]
	}
	return "you can only give permissions you hold yourself; you do not hold " + strings.Join(shown, ", ") + more
}

// Actor is the signed-in caller of a role change.
type Actor struct {
	UserID uuid.UUID
	// Subject is the token's user id; a user's row may carry it as external_id only.
	Subject       string
	PlatformOwner bool
	// Admin holds erp_admin.
	Admin bool
	// Holds reports whether the caller has a permission, from the token or a local role.
	Holds func(code string) bool
}

// exempt callers may hand out anything (but never change their own roles).
func (a Actor) exempt() bool { return a.PlatformOwner || a.Admin }

// checkGrant refuses codes the caller does not hold.
func (a Actor) checkGrant(codes []string) error {
	if a.exempt() {
		return nil
	}
	var missing []string
	for _, c := range codes {
		if a.Holds == nil || !a.Holds(c) {
			missing = append(missing, c)
		}
	}
	if len(missing) > 0 {
		slices.Sort(missing)
		return &BeyondGrantError{missing}
	}
	return nil
}

// HasAdminRole reports whether the user holds the shared erp_admin role in the tenant.
func (s *Service) HasAdminRole(ctx context.Context, tenantID, userID uuid.UUID) (bool, error) {
	return s.orm.UserRoleAssignment.Query().Where(
		userroleassignment.TenantID(tenantID), userroleassignment.UserID(userID),
		userroleassignment.HasRoleWith(role.TenantIDIsNil(), role.RoleCode(wildcardRoleCode)),
	).Exist(ctx)
}

// refuseOwn refuses a change of the caller's own assignments.
func (s *Service) refuseOwn(ctx context.Context, a Actor, userID uuid.UUID) error {
	if a.UserID != uuid.Nil && a.UserID == userID {
		return ErrOwnRoles
	}
	if a.Subject == "" {
		return nil
	}
	own, err := s.orm.CustomUser.Query().Where(customuser.ID(userID), customuser.ExternalID(a.Subject)).Exist(ctx)
	if err != nil {
		return err
	}
	if own {
		return ErrOwnRoles
	}
	return nil
}

// roleCodes are the permission codes of a role.
func roleCodes(ctx context.Context, r *ent.Role) ([]string, error) {
	return r.QueryPermissions().Select(permission.FieldPermissionCode).Strings(ctx)
}

// checkAssign refuses a role that gives more than the caller holds. The administrator role is
// only given by an administrator, whatever permissions its row carries.
func (s *Service) checkAssign(ctx context.Context, a Actor, r *ent.Role) error {
	if a.exempt() {
		return nil
	}
	if r.RoleCode == wildcardRoleCode {
		return ErrAdminOnlyRole
	}
	codes, err := roleCodes(ctx, r)
	if err != nil {
		return fmt.Errorf("rbac: load role permissions: %w", err)
	}
	return a.checkGrant(codes)
}

// RemoveUserRole revokes a role from one of the tenant's users. The last erp_admin assignment of
// a company stays; the assignments are locked, so two removals cannot both pass the check.
func (s *Service) RemoveUserRole(ctx context.Context, a Actor, tenantID, userID, roleID uuid.UUID) error {
	if err := s.refuseOwn(ctx, a, userID); err != nil {
		return err
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return fmt.Errorf("rbac: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()
	// Usually one shared erp_admin row; more only if a seed ever created a second.
	adminRoles, err := tx.Role.Query().Where(role.TenantIDIsNil(), role.RoleCode(wildcardRoleCode)).IDs(ctx)
	if err != nil {
		return fmt.Errorf("rbac: load administrator role: %w", err)
	}
	admins, err := tx.UserRoleAssignment.Query().Where(
		userroleassignment.TenantID(tenantID),
		userroleassignment.RoleIDIn(adminRoles...),
	).Order(ent.Asc(userroleassignment.FieldID)).ForUpdate().All(ctx)
	if err != nil {
		return fmt.Errorf("rbac: lock administrators: %w", err)
	}
	others, target := 0, false
	for _, as := range admins {
		if as.UserID == userID && as.RoleID == roleID {
			target = true
		} else if as.UserID != userID {
			others++
		}
	}
	if target && others == 0 {
		return ErrLastAdmin
	}
	if _, err := tx.UserRoleAssignment.Delete().Where(
		userroleassignment.TenantID(tenantID), userroleassignment.UserID(userID), userroleassignment.RoleID(roleID),
	).Exec(ctx); err != nil {
		return fmt.Errorf("rbac: remove assignment: %w", err)
	}
	return tx.Commit()
}
