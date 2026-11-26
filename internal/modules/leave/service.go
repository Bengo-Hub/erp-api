// Package leave implements tenant-isolated leave management: categories, entitlements,
// requests with an approval state machine, balances, public holidays, and the accrual
// cron.
package leave

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaveentitlement"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavelog"
	"github.com/Bengo-Hub/erp-api/internal/ent/publicholiday"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
	"github.com/Bengo-Hub/erp-api/internal/modules/holidays"
)

// Service holds leave CRUD + balance/accrual logic. Every query is tenant-scoped.
type Service struct {
	orm       *ent.Client
	notify    Notifier
	approvals Approver
	// systemTenant owns the GLOBAL shared leave types; a tenant with none of its own inherits
	// them (feedback_shared_core_reference_data). uuid.Nil = no fallback.
	systemTenant uuid.UUID
	calendar     WorkCalendar // working day source for counting requests (days.go)
}

// Notifier publishes leave-decision notifications to the outbox (erp.notification.requested).
// Optional — nil disables notifications (the service still functions).
type Notifier interface {
	NotifyLeaveDecision(ctx context.Context, tenantID uuid.UUID, req *ent.LeaveRequest) error
}

// Approver is the slice of the approvals engine the leave module needs. When a tenant has
// configured a leave_request approval workflow, leave decisions route through it (Sprint 4);
// otherwise the leave module falls back to its direct pending->approved/rejected path.
type Approver interface {
	Submit(ctx context.Context, tenantID uuid.UUID, in approvals.SubmitInput) (*ent.ApprovalRequest, error)
	FindRequestForObject(ctx context.Context, tenantID uuid.UUID, module string, objectID uuid.UUID) (*ent.ApprovalRequest, error)
	Decide(ctx context.Context, tenantID uuid.UUID, in approvals.DecisionInput) (*approvals.Decision, error)
}

func NewService(orm *ent.Client, notify Notifier) *Service {
	return &Service{orm: orm, notify: notify}
}

// WithSystemTenant sets the global-leave-types fallback tenant (chainable, startup wiring).
func (s *Service) WithSystemTenant(id uuid.UUID) *Service { s.systemTenant = id; return s }

// ---- Categories ----

// ListCategories returns the leave types a company uses, by name: its own, and the platform's
// (with the company's changes) that no own type of the same name replaces (inherit.go).
func (s *Service) ListCategories(ctx context.Context, tenantID uuid.UUID) ([]*ent.LeaveCategory, error) {
	rows, _, err := s.resolvedCategories(ctx, tenantID)
	return rows, err
}

// CategoryInput is the create/update payload for a leave category.
type CategoryInput struct {
	Name              string
	Description       string
	IsActive          bool
	IsPaid            bool
	DefaultAnnualDays decimal.Decimal
	AllowCarryover    bool
	MaxCarryoverDays  decimal.Decimal
}

// CreateCategory inserts a tenant-scoped leave category.
func (s *Service) CreateCategory(ctx context.Context, tenantID uuid.UUID, in CategoryInput) (*ent.LeaveCategory, error) {
	if err := s.ensureUniqueCategoryName(ctx, tenantID, in.Name, nil); err != nil {
		return nil, err
	}
	row, err := s.orm.LeaveCategory.Create().
		SetTenantID(tenantID).
		SetName(in.Name).
		SetDescription(in.Description).
		SetIsActive(in.IsActive).
		SetIsPaid(in.IsPaid).
		SetDefaultAnnualDays(in.DefaultAnnualDays).
		SetAllowCarryover(in.AllowCarryover).
		SetMaxCarryoverDays(in.MaxCarryoverDays).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: create category: %w", err)
	}
	return row, nil
}

// OwnCategory loads one of the tenant's own leave types for an edit; a platform type answers
// ErrInheritedCategory.
func (s *Service) OwnCategory(ctx context.Context, tenantID, id uuid.UUID) (*ent.LeaveCategory, error) {
	row, err := s.orm.LeaveCategory.Query().Where(leavecategory.TenantID(tenantID), leavecategory.ID(id)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, s.missingCategory(ctx, tenantID, id)
	}
	return row, err
}

// UpdateCategory updates a tenant-scoped leave category.
func (s *Service) UpdateCategory(ctx context.Context, tenantID, id uuid.UUID, in CategoryInput) (*ent.LeaveCategory, error) {
	if err := s.ensureUniqueCategoryName(ctx, tenantID, in.Name, &id); err != nil {
		return nil, err
	}
	n, err := s.orm.LeaveCategory.Update().
		Where(leavecategory.TenantID(tenantID), leavecategory.ID(id)).
		SetName(in.Name).
		SetDescription(in.Description).
		SetIsActive(in.IsActive).
		SetIsPaid(in.IsPaid).
		SetDefaultAnnualDays(in.DefaultAnnualDays).
		SetAllowCarryover(in.AllowCarryover).
		SetMaxCarryoverDays(in.MaxCarryoverDays).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: update category: %w", err)
	}
	if n == 0 {
		return nil, s.missingCategory(ctx, tenantID, id)
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
		return s.missingCategory(ctx, tenantID, id)
	}
	return nil
}

// missingCategory explains an edit that matched none of the tenant's own leave types.
func (s *Service) missingCategory(ctx context.Context, tenantID, id uuid.UUID) error {
	if _, err := s.usableCategory(ctx, tenantID, id); err == nil {
		return ErrInheritedCategory
	}
	return ErrUnknownCategory
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
	if ok, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.ID(employeeID)).Exist(ctx); err != nil {
		return nil, fmt.Errorf("leave: load employee: %w", err)
	} else if !ok {
		return nil, ErrEmployeeNotFound
	}
	if ok, err := s.orm.LeaveCategory.Query().Where(leavecategory.ID(categoryID),
		leavecategory.TenantIDIn(tenantID, s.systemTenant)).Exist(ctx); err != nil {
		return nil, fmt.Errorf("leave: load leave type: %w", err)
	} else if !ok {
		return nil, ErrUnknownCategory
	}
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

// BalanceView enriches a LeaveBalance with display names + the UI's field aliases
// (entitled/used/remaining mirror days_entitled/days_taken/days_remaining) so the
// frontend table renders real values instead of "—".
type BalanceView struct {
	*ent.LeaveBalance
	EmployeeName  string `json:"employee_name"`
	LeaveTypeName string `json:"leave_type_name"`
	Entitled      string `json:"entitled"`
	Used          string `json:"used"`
	Remaining     string `json:"remaining"`
}

// ListBalancesEnriched returns balances joined to employee + leave-category names.
func (s *Service) ListBalancesEnriched(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, year int) ([]BalanceView, error) {
	rows, err := s.ListBalances(ctx, tenantID, employeeID, year)
	if err != nil {
		return nil, err
	}
	empIDs := make([]uuid.UUID, 0, len(rows))
	catIDs := make([]uuid.UUID, 0, len(rows))
	for _, r := range rows {
		empIDs = append(empIDs, r.EmployeeID)
		catIDs = append(catIDs, r.CategoryID)
	}
	n, err := s.lookupNames(ctx, tenantID, empIDs, catIDs)
	if err != nil {
		return nil, err
	}
	out := make([]BalanceView, 0, len(rows))
	for _, r := range rows {
		out = append(out, BalanceView{
			LeaveBalance:  r,
			EmployeeName:  n.employee[r.EmployeeID],
			LeaveTypeName: n.category[r.CategoryID],
			Entitled:      r.DaysEntitled.String(),
			Used:          r.DaysTaken.String(),
			Remaining:     r.DaysRemaining.String(),
		})
	}
	return out, nil
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

// ListHolidays returns the tenant's own public holidays and the platform's national ones it
// inherits, each marked inherited and active (optionally for a year).
func (s *Service) ListHolidays(ctx context.Context, tenantID uuid.UUID, year int) ([]holidays.Holiday, error) {
	var from, to time.Time
	if year > 0 {
		from = time.Date(year, 1, 1, 0, 0, 0, 0, time.UTC)
		to = time.Date(year+1, 1, 1, 0, 0, 0, 0, time.UTC)
	}
	return holidays.List(ctx, s.orm, s.systemTenant, tenantID, from, to)
}

// SetHolidayActive switches one of the platform's holidays off or back on for the tenant.
func (s *Service) SetHolidayActive(ctx context.Context, tenantID, id uuid.UUID, active bool) (*holidays.Holiday, error) {
	h, err := holidays.SetActive(ctx, s.orm, s.systemTenant, tenantID, id, active)
	if errors.Is(err, holidays.ErrNotInherited) {
		return nil, ErrHolidayNotFound
	}
	return h, err
}

// SystemTenant is the tenant whose rows every tenant inherits (uuid.Nil when unset).
func (s *Service) SystemTenant() uuid.UUID { return s.systemTenant }

// ErrHolidayNotFound is returned when a holiday id does not exist for the tenant (another
// tenant's row included), so handlers can answer 404.
var ErrHolidayNotFound = errors.New("holiday not found")

// HolidayInput is the create and update payload for a public holiday. A national holiday has no
// county; a county holiday must name one.
type HolidayInput struct {
	Name       string
	Date       time.Time
	IsNational bool
	County     string
}

func (in *HolidayInput) normalise() error {
	in.Name = strings.TrimSpace(in.Name)
	in.County = strings.TrimSpace(in.County)
	if in.Name == "" {
		return errors.New("name is required")
	}
	if in.IsNational {
		in.County = ""
	} else if in.County == "" {
		return errors.New("county is required for a county holiday")
	}
	return nil
}

// CreateHoliday inserts a tenant-scoped public holiday.
func (s *Service) CreateHoliday(ctx context.Context, tenantID uuid.UUID, in HolidayInput) (*ent.PublicHoliday, error) {
	if err := in.normalise(); err != nil {
		return nil, err
	}
	b := s.orm.PublicHoliday.Create().
		SetTenantID(tenantID).SetName(in.Name).SetDate(in.Date).SetIsNational(in.IsNational)
	if in.County != "" {
		b = b.SetCounty(in.County)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: create holiday: %w", err)
	}
	return row, nil
}

// UpdateHoliday edits a tenant-scoped public holiday with the create validation.
func (s *Service) UpdateHoliday(ctx context.Context, tenantID, id uuid.UUID, in HolidayInput) (*ent.PublicHoliday, error) {
	if err := in.normalise(); err != nil {
		return nil, err
	}
	existing, err := s.orm.PublicHoliday.Query().
		Where(publicholiday.TenantID(tenantID), publicholiday.ID(id)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrHolidayNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("leave: load holiday: %w", err)
	}
	u := existing.Update().SetName(in.Name).SetDate(in.Date).SetIsNational(in.IsNational)
	if in.County != "" {
		u = u.SetCounty(in.County)
	} else {
		u = u.ClearCounty()
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: update holiday: %w", err)
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
		return ErrHolidayNotFound
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
