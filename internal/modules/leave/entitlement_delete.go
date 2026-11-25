package leave

import (
	"context"
	"errors"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaveentitlement"
)

// ErrEntitlementNotFound is returned for an entitlement id the tenant does not have.
var ErrEntitlementNotFound = errors.New("entitlement not found")

// DeleteEntitlement removes a person's own entitlement and, like the daily accrual, sets their
// existing balance of that type and year back to the type's default days plus any carryover.
// Days already taken stay. A missing balance is not created.
func (s *Service) DeleteEntitlement(ctx context.Context, tenantID, id uuid.UUID) error {
	row, err := s.orm.LeaveEntitlement.Query().
		Where(leaveentitlement.TenantID(tenantID), leaveentitlement.ID(id)).Only(ctx)
	if ent.IsNotFound(err) {
		return ErrEntitlementNotFound
	}
	if err != nil {
		return fmt.Errorf("leave: load entitlement: %w", err)
	}
	if err := s.orm.LeaveEntitlement.DeleteOne(row).Exec(ctx); err != nil {
		return fmt.Errorf("leave: delete entitlement: %w", err)
	}
	exists, err := s.orm.LeaveBalance.Query().Where(
		leavebalance.TenantID(tenantID), leavebalance.EmployeeID(row.EmployeeID),
		leavebalance.CategoryID(row.CategoryID), leavebalance.Year(row.Year)).Exist(ctx)
	if err != nil || !exists {
		return err
	}
	cat, err := s.orm.LeaveCategory.Query().Where(leavecategory.ID(row.CategoryID),
		leavecategory.TenantIDIn(tenantID, s.systemTenant)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("leave: load leave type: %w", err)
	}
	entitled, err := s.computeEntitled(ctx, tenantID, row.EmployeeID, cat, row.Year, row.Year-1)
	if err != nil {
		return err
	}
	return s.refreshBalance(ctx, tenantID, row.EmployeeID, row.CategoryID, row.Year, entitled)
}
