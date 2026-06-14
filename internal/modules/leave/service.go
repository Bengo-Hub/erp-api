// Package leave implements tenant-isolated leave management: categories, entitlements,
// requests with an approval state machine, balances, public holidays, and the accrual
// cron (Go replacement for the Django accrue_leave management command).
package leave

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaveentitlement"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavelog"
	"github.com/Bengo-Hub/erp-api/internal/ent/publicholiday"
)

// Service holds leave CRUD + balance/accrual logic. Every query is tenant-scoped.
type Service struct {
	orm    *ent.Client
	notify Notifier
}

// Notifier publishes leave-decision notifications to the outbox (erp.notification.requested).
// Optional — nil disables notifications (the service still functions).
type Notifier interface {
	NotifyLeaveDecision(ctx context.Context, tenantID uuid.UUID, req *ent.LeaveRequest) error
}

func NewService(orm *ent.Client, notify Notifier) *Service {
	return &Service{orm: orm, notify: notify}
}

// ---- Categories ----

// ListCategories returns tenant-scoped leave categories.
func (s *Service) ListCategories(ctx context.Context, tenantID uuid.UUID) ([]*ent.LeaveCategory, error) {
	return s.orm.LeaveCategory.Query().
		Where(leavecategory.TenantID(tenantID)).
		Order(ent.Asc(leavecategory.FieldName)).All(ctx)
}

// CategoryInput is the create/update payload for a leave category.
type CategoryInput struct {
	Name              string
	Description       string
	IsActive          bool
	DefaultAnnualDays decimal.Decimal
	AllowCarryover    bool
	MaxCarryoverDays  decimal.Decimal
}

// CreateCategory inserts a tenant-scoped leave category.
func (s *Service) CreateCategory(ctx context.Context, tenantID uuid.UUID, in CategoryInput) (*ent.LeaveCategory, error) {
	row, err := s.orm.LeaveCategory.Create().
		SetTenantID(tenantID).
		SetName(in.Name).
		SetDescription(in.Description).
		SetIsActive(in.IsActive).
		SetDefaultAnnualDays(in.DefaultAnnualDays).
		SetAllowCarryover(in.AllowCarryover).
		SetMaxCarryoverDays(in.MaxCarryoverDays).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: create category: %w", err)
	}
	return row, nil
}

// UpdateCategory updates a tenant-scoped leave category.
func (s *Service) UpdateCategory(ctx context.Context, tenantID, id uuid.UUID, in CategoryInput) (*ent.LeaveCategory, error) {
	n, err := s.orm.LeaveCategory.Update().
		Where(leavecategory.TenantID(tenantID), leavecategory.ID(id)).
		SetName(in.Name).
		SetDescription(in.Description).
		SetIsActive(in.IsActive).
		SetDefaultAnnualDays(in.DefaultAnnualDays).
		SetAllowCarryover(in.AllowCarryover).
		SetMaxCarryoverDays(in.MaxCarryoverDays).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: update category: %w", err)
	}
	if n == 0 {
		return nil, fmt.Errorf("leave: category not found")
	}
	return s.orm.LeaveCategory.Query().
		Where(leavecategory.TenantID(tenantID), leavecategory.ID(id)).Only(ctx)
}

// DeleteCategory removes a tenant-scoped leave category.
func (s *Service) DeleteCategory(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.LeaveCategory.Delete().
		Where(leavecategory.TenantID(tenantID), leavecategory.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("leave: delete category: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("leave: category not found")
	}
	return nil
}

// ---- Entitlements ----

// ListEntitlements returns entitlements filtered by tenant (+ optional employee/year).
func (s *Service) ListEntitlements(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, year int) ([]*ent.LeaveEntitlement, error) {
	q := s.orm.LeaveEntitlement.Query().Where(leaveentitlement.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(leaveentitlement.EmployeeID(*employeeID))
	}
	if year > 0 {
		q = q.Where(leaveentitlement.Year(year))
	}
	return q.Order(ent.Desc(leaveentitlement.FieldYear)).All(ctx)
}

// UpsertEntitlement sets an employee's entitled days for a category/year and keeps the
// matching LeaveBalance in sync (entitled changes propagate to remaining).
func (s *Service) UpsertEntitlement(ctx context.Context, tenantID, employeeID, categoryID uuid.UUID, year int, days decimal.Decimal) (*ent.LeaveEntitlement, error) {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	existing, err := tx.LeaveEntitlement.Query().Where(
		leaveentitlement.TenantID(tenantID),
		leaveentitlement.EmployeeID(employeeID),
		leaveentitlement.CategoryID(categoryID),
		leaveentitlement.Year(year),
	).First(ctx)

	var ent0 *ent.LeaveEntitlement
	if ent.IsNotFound(err) {
		ent0, err = tx.LeaveEntitlement.Create().
			SetTenantID(tenantID).SetEmployeeID(employeeID).SetCategoryID(categoryID).
			SetYear(year).SetDaysEntitled(days).Save(ctx)
	} else if err == nil {
		ent0, err = existing.Update().SetDaysEntitled(days).Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("leave: upsert entitlement: %w", err)
	}

	if err := upsertBalanceTx(ctx, tx, tenantID, employeeID, categoryID, year, days); err != nil {
		return nil, err
	}
	if err := tx.Commit(); err != nil {
		return nil, fmt.Errorf("leave: commit entitlement: %w", err)
	}
	return ent0, nil
}

// ---- Balances ----

// ListBalances returns balances filtered by tenant (+ optional employee/year).
func (s *Service) ListBalances(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, year int) ([]*ent.LeaveBalance, error) {
	q := s.orm.LeaveBalance.Query().Where(leavebalance.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(leavebalance.EmployeeID(*employeeID))
	}
	if year > 0 {
		q = q.Where(leavebalance.Year(year))
	}
	return q.Order(ent.Desc(leavebalance.FieldYear)).All(ctx)
}

// upsertBalanceTx creates/updates a balance row so days_entitled == entitled and
// days_remaining == entitled - days_taken (taken preserved on update). Tx-scoped.
func upsertBalanceTx(ctx context.Context, tx *ent.Tx, tenantID, employeeID, categoryID uuid.UUID, year int, entitled decimal.Decimal) error {
	bal, err := tx.LeaveBalance.Query().Where(
		leavebalance.TenantID(tenantID),
		leavebalance.EmployeeID(employeeID),
		leavebalance.CategoryID(categoryID),
		leavebalance.Year(year),
	).First(ctx)
	if ent.IsNotFound(err) {
		_, cerr := tx.LeaveBalance.Create().
			SetTenantID(tenantID).SetEmployeeID(employeeID).SetCategoryID(categoryID).
			SetYear(year).SetDaysEntitled(entitled).SetDaysTaken(decimal.Zero).
			SetDaysRemaining(entitled).Save(ctx)
		if cerr != nil {
			return fmt.Errorf("leave: create balance: %w", cerr)
		}
		return nil
	}
	if err != nil {
		return fmt.Errorf("leave: balance lookup: %w", err)
	}
	remaining := entitled.Sub(bal.DaysTaken)
	if _, uerr := bal.Update().SetDaysEntitled(entitled).SetDaysRemaining(remaining).Save(ctx); uerr != nil {
		return fmt.Errorf("leave: update balance: %w", uerr)
	}
	return nil
}

// ---- Public holidays ----

// ListHolidays returns tenant-scoped public holidays (optionally for a year).
func (s *Service) ListHolidays(ctx context.Context, tenantID uuid.UUID, year int) ([]*ent.PublicHoliday, error) {
	q := s.orm.PublicHoliday.Query().Where(publicholiday.TenantID(tenantID))
	if year > 0 {
		start := time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC)
		end := time.Date(year+1, 1, 1, 0, 0, 0, 0, time.UTC)
		q = q.Where(publicholiday.DateGTE(start), publicholiday.DateLT(end))
	}
	return q.Order(ent.Desc(publicholiday.FieldDate)).All(ctx)
}

// CreateHoliday inserts a tenant-scoped public holiday.
func (s *Service) CreateHoliday(ctx context.Context, tenantID uuid.UUID, name string, date time.Time, isNational bool, county string) (*ent.PublicHoliday, error) {
	b := s.orm.PublicHoliday.Create().
		SetTenantID(tenantID).SetName(name).SetDate(date).SetIsNational(isNational)
	if county != "" {
		b = b.SetCounty(county)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: create holiday: %w", err)
	}
	return row, nil
}

// DeleteHoliday removes a tenant-scoped public holiday.
func (s *Service) DeleteHoliday(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.PublicHoliday.Delete().
		Where(publicholiday.TenantID(tenantID), publicholiday.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("leave: delete holiday: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("leave: holiday not found")
	}
	return nil
}

// logAction appends a LeaveLog audit row (best-effort within the caller's context).
func logAction(ctx context.Context, c *ent.Client, tenantID, reqID uuid.UUID, action leavelog.Action, desc string, userID *uuid.UUID) {
	b := c.LeaveLog.Create().
		SetTenantID(tenantID).SetLeaveRequestID(reqID).SetAction(action).SetDescription(desc)
	if userID != nil {
		b = b.SetUserID(*userID)
	}
	_, _ = b.Save(ctx)
}
