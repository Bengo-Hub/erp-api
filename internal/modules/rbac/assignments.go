package rbac

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/customuser"
	"github.com/Bengo-Hub/erp-api/internal/ent/predicate"
	"github.com/Bengo-Hub/erp-api/internal/ent/role"
	"github.com/Bengo-Hub/erp-api/internal/ent/userroleassignment"
)

// Where an assignment came from. Sign-in (the SSO token) adds and removes only its own.
const (
	SourceSync = "sync"
	SourceERP  = "erp"
)

// Members answers whether an auth user is an active member of a tenant (platform/auth asks
// auth-api).
type Members interface {
	ActiveMember(ctx context.Context, tenantID, userID string) (bool, error)
}

// WithMembers sets the member lookup; nil (local development) trusts every member.
func (s *Service) WithMembers(m Members) *Service { s.members = m; return s }

// notExpired keeps assignments without an expiry, or with one still ahead.
func notExpired() predicate.UserRoleAssignment {
	return userroleassignment.Or(userroleassignment.ExpiresAtIsNil(), userroleassignment.ExpiresAtGT(time.Now()))
}

// liveAssignments are the assignments that count for a user now. A role given in ERP counts only
// while auth-api lists the person as an active member; when that cannot be known it does not
// count, and the sign-in roles still do.
func (s *Service) liveAssignments(ctx context.Context, tenantID, userID uuid.UUID) ([]*ent.UserRoleAssignment, error) {
	rows, err := s.orm.UserRoleAssignment.Query().
		Where(userroleassignment.TenantID(tenantID), userroleassignment.UserID(userID), notExpired()).All(ctx)
	if err != nil || s.members == nil {
		return rows, err
	}
	out := make([]*ent.UserRoleAssignment, 0, len(rows))
	checked, member := false, false
	for _, a := range rows {
		if a.Source == SourceERP {
			if !checked {
				checked, member = true, s.activeMember(ctx, tenantID, userID)
			}
			if !member {
				continue
			}
		}
		out = append(out, a)
	}
	return out, nil
}

// activeMember looks a local user up in auth-api's member list, by the id auth-api knows.
func (s *Service) activeMember(ctx context.Context, tenantID, userID uuid.UUID) bool {
	u, err := s.orm.CustomUser.Query().Where(customuser.ID(userID)).Only(ctx)
	if err != nil {
		return false
	}
	ok, err := s.members.ActiveMember(ctx, tenantID.String(), u.ExternalID)
	if err != nil {
		s.log.Warn("member lookup failed; roles given in ERP are not applied", zap.String("tenant", tenantID.String()), zap.Error(err))
		return false
	}
	return ok
}

// HasAdminRole reports whether the user holds the shared erp_admin role in the tenant now.
func (s *Service) HasAdminRole(ctx context.Context, tenantID, userID uuid.UUID) (bool, error) {
	rows, err := s.liveAssignments(ctx, tenantID, userID)
	if err != nil || len(rows) == 0 {
		return false, err
	}
	ids := make([]uuid.UUID, len(rows))
	for i, a := range rows {
		ids[i] = a.RoleID
	}
	return s.orm.Role.Query().Where(role.IDIn(ids...), role.TenantIDIsNil(), role.RoleCode(wildcardRoleCode)).Exist(ctx)
}

// RevokeGiven removes every role given in ERP to a person whose account was deactivated, in every
// company. Reactivating the account does not bring them back; someone gives them again.
func (s *Service) RevokeGiven(ctx context.Context, externalID string) (int, error) {
	n, err := s.orm.UserRoleAssignment.Delete().Where(
		userroleassignment.Source(SourceERP),
		userroleassignment.HasUserWith(customuser.ExternalID(externalID)),
	).Exec(ctx)
	if err != nil {
		return 0, fmt.Errorf("rbac: revoke given roles: %w", err)
	}
	return n, nil
}
