package leave

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaveentitlement"
)

// AccrueResult reports rows processed by an accrual run.
type AccrueResult struct {
	Year      int
	Processed int
}

// AccrueYear establishes/refreshes leave balances for a tenant's year with year-end
// carryover (port of accrue_leave.py). Idempotent: re-running never clobbers already-taken
// days — it only refreshes entitled/remaining. For each active employee × active category:
//
//	entitled = (explicit entitlement OR category.default_annual_days)
//	         + carryover(prev-year remaining, capped by max_carryover_days when allow_carryover)
func (s *Service) AccrueYear(ctx context.Context, tenantID uuid.UUID, year int) (AccrueResult, error) {
	res := AccrueResult{Year: year}
	prev := year - 1

	emps, err := s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.Deleted(false), employee.Terminated(false)).
		All(ctx)
	if err != nil {
		return res, fmt.Errorf("leave: accrual employees: %w", err)
	}
	cats, err := s.orm.LeaveCategory.Query().
		Where(leavecategory.TenantID(tenantID), leavecategory.IsActive(true)).All(ctx)
	if err != nil {
		return res, fmt.Errorf("leave: accrual categories: %w", err)
	}

	for _, emp := range emps {
		for _, cat := range cats {
			entitled, err := s.computeEntitled(ctx, tenantID, emp.ID, cat, year, prev)
			if err != nil {
				return res, err
			}
			if err := s.refreshBalance(ctx, tenantID, emp.ID, cat.ID, year, entitled); err != nil {
				return res, err
			}
			res.Processed++
		}
	}
	return res, nil
}

// computeEntitled resolves base entitlement + capped carryover for one employee/category.
func (s *Service) computeEntitled(ctx context.Context, tenantID, employeeID uuid.UUID, cat *ent.LeaveCategory, year, prev int) (decimal.Decimal, error) {
	base := cat.DefaultAnnualDays
	if ovr, err := s.orm.LeaveEntitlement.Query().Where(
		leaveentitlement.TenantID(tenantID),
		leaveentitlement.EmployeeID(employeeID),
		leaveentitlement.CategoryID(cat.ID),
		leaveentitlement.Year(year),
	).First(ctx); err == nil {
		base = ovr.DaysEntitled
	} else if !ent.IsNotFound(err) {
		return decimal.Zero, fmt.Errorf("leave: entitlement override: %w", err)
	}

	carry := decimal.Zero
	if cat.AllowCarryover {
		if prevBal, err := s.orm.LeaveBalance.Query().Where(
			leavebalance.TenantID(tenantID),
			leavebalance.EmployeeID(employeeID),
			leavebalance.CategoryID(cat.ID),
			leavebalance.Year(prev),
		).First(ctx); err == nil {
			carry = prevBal.DaysRemaining
			if carry.LessThan(decimal.Zero) {
				carry = decimal.Zero
			}
			if cat.MaxCarryoverDays.GreaterThan(decimal.Zero) && carry.GreaterThan(cat.MaxCarryoverDays) {
				carry = cat.MaxCarryoverDays
			}
		} else if !ent.IsNotFound(err) {
			return decimal.Zero, fmt.Errorf("leave: prev balance: %w", err)
		}
	}
	return base.Add(carry), nil
}

// refreshBalance creates/updates a balance row: entitled set, remaining = entitled - taken
// (floored at 0), taken preserved. Idempotent.
func (s *Service) refreshBalance(ctx context.Context, tenantID, employeeID, categoryID uuid.UUID, year int, entitled decimal.Decimal) error {
	bal, err := s.orm.LeaveBalance.Query().Where(
		leavebalance.TenantID(tenantID),
		leavebalance.EmployeeID(employeeID),
		leavebalance.CategoryID(categoryID),
		leavebalance.Year(year),
	).First(ctx)
	if ent.IsNotFound(err) {
		_, cerr := s.orm.LeaveBalance.Create().
			SetTenantID(tenantID).SetEmployeeID(employeeID).SetCategoryID(categoryID).
			SetYear(year).SetDaysEntitled(entitled).SetDaysTaken(decimal.Zero).
			SetDaysRemaining(entitled).Save(ctx)
		if cerr != nil {
			return fmt.Errorf("leave: accrual create balance: %w", cerr)
		}
		return nil
	}
	if err != nil {
		return fmt.Errorf("leave: accrual balance lookup: %w", err)
	}
	remaining := entitled.Sub(bal.DaysTaken)
	if remaining.LessThan(decimal.Zero) {
		remaining = decimal.Zero
	}
	if _, uerr := bal.Update().SetDaysEntitled(entitled).SetDaysRemaining(remaining).Save(ctx); uerr != nil {
		return fmt.Errorf("leave: accrual update balance: %w", uerr)
	}
	return nil
}

// AccrueAllTenants runs accrual for every tenant that has at least one active leave category.
// Used by the scheduled accrual cron goroutine.
func (s *Service) AccrueAllTenants(ctx context.Context, year int) (int, error) {
	tenantIDs, err := s.orm.LeaveCategory.Query().
		Where(leavecategory.IsActive(true)).
		GroupBy(leavecategory.FieldTenantID).Strings(ctx)
	if err != nil {
		return 0, fmt.Errorf("leave: accrual tenants: %w", err)
	}
	total := 0
	for _, t := range tenantIDs {
		tid, perr := uuid.Parse(t)
		if perr != nil {
			continue
		}
		res, rerr := s.AccrueYear(ctx, tid, year)
		if rerr != nil {
			return total, rerr
		}
		total += res.Processed
	}
	return total, nil
}
