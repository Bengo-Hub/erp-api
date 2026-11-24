package leave

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavebalance"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// How a leave type's days are counted.
const (
	CountWorkingDays  = "working_days"
	CountCalendarDays = "calendar_days"
)

// CountModesKey is the AppSetting key holding a tenant's count mode per leave type (a JSON object
// keyed by category id). Only changed types are stored, so platform leave types are not copied.
const CountModesKey = "leave.count_modes"

// Readable request errors.
var (
	ErrEmployeeNotFound = errors.New("employee not found")
	ErrUnknownCategory  = errors.New("unknown leave type")
	ErrRequestNotFound  = errors.New("leave request not found")
	ErrDateOrder        = errors.New("the end date must not be before the start date")
	ErrNoDays           = errors.New("these dates have no working days for this employee, so there is nothing to apply for")
	ErrCountMode        = errors.New("count mode must be working_days or calendar_days")
	ErrNoCalendar       = errors.New("working days cannot be counted right now")
)

// WorkCalendar answers an employee's planned days; the attendance service implements it. The
// attendance module does not import leave, so there is no import cycle.
type WorkCalendar interface {
	PlannedDays(ctx context.Context, tenantID, employeeID uuid.UUID, from, to time.Time) ([]attendance.PlannedDay, error)
}

// SetCalendar wires the working day source (called at startup).
func (s *Service) SetCalendar(c WorkCalendar) { s.calendar = c }

// CategoryView is a leave type with the way its days are counted for the tenant.
type CategoryView struct {
	*ent.LeaveCategory
	CountMode string `json:"count_mode"`
}

// SkippedDay is a date that does not count as a full day, with the reason.
type SkippedDay struct {
	Date   string          `json:"date"`
	Reason string          `json:"reason"`
	Name   string          `json:"name,omitempty"`
	Share  decimal.Decimal `json:"counted"`
}

// Preview is what filing a request would count. RemainingBalance is nil when the employee has no
// balance for the type in the year of the start date.
type Preview struct {
	Days             decimal.Decimal  `json:"days"`
	CountMode        string           `json:"count_mode"`
	Skipped          []SkippedDay     `json:"skipped"`
	BalanceYear      int              `json:"balance_year"`
	RemainingBalance *decimal.Decimal `json:"remaining_balance"`
}

func utcDay(t time.Time) time.Time {
	y, m, d := t.UTC().Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

// defaultCountMode is the mode of a type nobody changed: maternity and paternity leave count
// calendar days, everything else working days.
func defaultCountMode(name string) string {
	n := strings.ToLower(name)
	if strings.Contains(n, "maternity") || strings.Contains(n, "paternity") {
		return CountCalendarDays
	}
	return CountWorkingDays
}

func (s *Service) countModes(ctx context.Context, c *ent.Client, tenantID uuid.UUID) (map[string]string, error) {
	modes := map[string]string{}
	row, err := c.AppSetting.Query().Where(appsetting.TenantID(tenantID), appsetting.AppKey(CountModesKey)).Only(ctx)
	if ent.IsNotFound(err) {
		return modes, nil
	}
	if err != nil {
		return nil, fmt.Errorf("leave: load count modes: %w", err)
	}
	if row.Value != "" {
		if err := json.Unmarshal([]byte(row.Value), &modes); err != nil {
			return nil, fmt.Errorf("leave: decode count modes: %w", err)
		}
	}
	return modes, nil
}

func modeOf(modes map[string]string, c *ent.LeaveCategory) string {
	if m := modes[c.ID.String()]; m == CountWorkingDays || m == CountCalendarDays {
		return m
	}
	return defaultCountMode(c.Name)
}

// CategoryViews adds the count mode to leave types.
func (s *Service) CategoryViews(ctx context.Context, tenantID uuid.UUID, rows []*ent.LeaveCategory) ([]CategoryView, error) {
	modes, err := s.countModes(ctx, s.orm, tenantID)
	if err != nil {
		return nil, err
	}
	out := make([]CategoryView, len(rows))
	for i, c := range rows {
		out[i] = CategoryView{LeaveCategory: c, CountMode: modeOf(modes, c)}
	}
	return out, nil
}

// SetCountMode stores how the tenant counts one of the leave types it uses, including a platform
// type it inherits.
func (s *Service) SetCountMode(ctx context.Context, tenantID, categoryID uuid.UUID, mode string) (*CategoryView, error) {
	if mode != CountWorkingDays && mode != CountCalendarDays {
		return nil, ErrCountMode
	}
	cat, err := s.usableCategory(ctx, tenantID, categoryID)
	if err != nil {
		return nil, err
	}
	modes, err := s.countModes(ctx, s.orm, tenantID)
	if err != nil {
		return nil, err
	}
	modes[categoryID.String()] = mode
	raw, err := json.Marshal(modes)
	if err != nil {
		return nil, err
	}
	err = s.orm.AppSetting.Create().
		SetTenantID(tenantID).SetAppKey(CountModesKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).
		UpdateNewValues().Exec(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: save count mode: %w", err)
	}
	return &CategoryView{LeaveCategory: cat, CountMode: mode}, nil
}

// usableCategory is a leave type the tenant sees in its list (its own, or an inherited one).
func (s *Service) usableCategory(ctx context.Context, tenantID, id uuid.UUID) (*ent.LeaveCategory, error) {
	rows, err := s.ListCategories(ctx, tenantID)
	if err != nil {
		return nil, fmt.Errorf("leave: load leave types: %w", err)
	}
	for _, c := range rows {
		if c.ID == id {
			return c, nil
		}
	}
	return nil, ErrUnknownCategory
}

// PreviewRequest counts the days a request would take and reports the dates it skips.
func (s *Service) PreviewRequest(ctx context.Context, tenantID, employeeID, categoryID uuid.UUID, start, end time.Time) (*Preview, error) {
	start, end = utcDay(start), utcDay(end)
	if end.Before(start) {
		return nil, ErrDateOrder
	}
	if end.Sub(start) >= attendance.MaxCapacityDays*24*time.Hour {
		return nil, attendance.ErrPlannedRange
	}
	exists, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.ID(employeeID), employee.Deleted(false)).Exist(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: load employee: %w", err)
	}
	if !exists {
		return nil, ErrEmployeeNotFound
	}
	cat, err := s.usableCategory(ctx, tenantID, categoryID)
	if err != nil {
		return nil, err
	}
	modes, err := s.countModes(ctx, s.orm, tenantID)
	if err != nil {
		return nil, err
	}
	p := &Preview{CountMode: modeOf(modes, cat), Skipped: []SkippedDay{}, BalanceYear: start.Year()}
	if p.CountMode == CountCalendarDays {
		p.Days = decimal.NewFromInt(int64(end.Sub(start).Hours()/24) + 1)
	} else {
		if s.calendar == nil {
			return nil, ErrNoCalendar
		}
		days, err := s.calendar.PlannedDays(ctx, tenantID, employeeID, start, end)
		if err != nil {
			return nil, err
		}
		for _, d := range days {
			p.Days = p.Days.Add(d.Share)
			if d.Reason != "" {
				p.Skipped = append(p.Skipped, SkippedDay{Date: d.Date.Format("2006-01-02"), Reason: d.Reason, Name: d.Name, Share: d.Share})
			}
		}
	}
	bal, err := s.orm.LeaveBalance.Query().Where(
		leavebalance.TenantID(tenantID), leavebalance.EmployeeID(employeeID),
		leavebalance.CategoryID(categoryID), leavebalance.Year(p.BalanceYear)).First(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return nil, fmt.Errorf("leave: load balance: %w", err)
	}
	if err == nil {
		p.RemainingBalance = &bal.DaysRemaining
	}
	return p, nil
}

// refuseOverlap rejects dates that touch another pending or approved request of the employee.
func refuseOverlap(ctx context.Context, tx *ent.Tx, tenantID, employeeID uuid.UUID, start, end time.Time) error {
	row, err := tx.LeaveRequest.Query().Where(
		leaverequest.TenantID(tenantID), leaverequest.EmployeeID(employeeID),
		leaverequest.StatusIn(leaverequest.StatusPending, leaverequest.StatusApproved),
		leaverequest.StartDateLT(end.AddDate(0, 0, 1)), leaverequest.EndDateGTE(start),
	).First(ctx)
	if ent.IsNotFound(err) {
		return nil
	}
	if err != nil {
		return fmt.Errorf("leave: check overlap: %w", err)
	}
	return fmt.Errorf("these dates overlap %s leave from %s to %s", row.Status,
		row.StartDate.Format("2006-01-02"), row.EndDate.Format("2006-01-02"))
}
