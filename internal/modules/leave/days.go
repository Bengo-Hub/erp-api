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
	ErrInactiveCategory = errors.New("this leave type is switched off and takes no new requests")
	// ErrInheritedCategory refuses an edit or delete of a platform leave type.
	ErrInheritedCategory = errors.New("this is a platform leave type and cannot be edited or deleted; you can change how its days are counted and its balance rule")
	ErrRequestNotFound   = errors.New("leave request not found")
	ErrDateOrder         = errors.New("the end date must not be before the start date")
	ErrNoDays            = errors.New("these dates have no working days for this employee, so there is nothing to apply for")
	ErrCountMode         = errors.New("count mode must be working_days or calendar_days")
	ErrNoCalendar        = errors.New("working days cannot be counted right now")
	ErrBothHalves        = errors.New("a one-day request is either the morning or the afternoon; for both, ask for the full day")
	ErrNotPendingEdit    = errors.New("only a pending request can be changed")
)

// RequestOptions are the parts of a request beyond its dates. StartHalfDay starts the leave at
// midday on the start date and EndHalfDay ends it at midday on the end date; on a one-day request
// they are the afternoon off and the morning off. Excluding is a pending request being edited,
// whose own days are not counted as pending and whose dates it may reuse.
type RequestOptions struct {
	StartHalfDay bool
	EndHalfDay   bool
	Excluding    uuid.UUID
}

// halfShare is what a half of a day counts: half of a full day, and never more than the day
// itself counts (a day off stays at nothing, a half working day at its half).
func halfShare(share decimal.Decimal) decimal.Decimal {
	return decimal.Min(share, decimal.NewFromFloat(0.5))
}

// WorkCalendar answers an employee's planned days; the attendance service implements it. The
// attendance module does not import leave, so there is no import cycle.
type WorkCalendar interface {
	PlannedDays(ctx context.Context, tenantID, employeeID uuid.UUID, from, to time.Time) ([]attendance.PlannedDay, error)
}

// SetCalendar wires the working day source (called at startup).
func (s *Service) SetCalendar(c WorkCalendar) { s.calendar = c }

// CategoryView is a leave type with the tenant's settings for it. Inherited marks a platform type,
// which the tenant cannot edit beyond those settings.
type CategoryView struct {
	*ent.LeaveCategory
	// IsActive is always sent (ent leaves a false one out of the JSON).
	IsActive    bool   `json:"is_active"`
	CountMode   string `json:"count_mode"`
	BalanceRule string `json:"balance_rule"`
	Inherited   bool   `json:"inherited"`
	// Customised marks an inherited type the company changed; revert drops the changes.
	Customised bool `json:"customised"`
}

// SkippedDay is a date that does not count as a full day, with the reason.
type SkippedDay struct {
	Date   string          `json:"date"`
	Reason string          `json:"reason"`
	Name   string          `json:"name,omitempty"`
	Share  decimal.Decimal `json:"counted"`
}

// Preview is what filing a request would count. RemainingBalance is nil when the employee has no
// balance for the type in the year of the start date; AvailableBalance takes off their pending
// requests. Refused tells whether filing would be refused for the balance; BalanceMessage is the
// reason, or the warning when the type allows it.
type Preview struct {
	Days             decimal.Decimal  `json:"days"`
	CountMode        string           `json:"count_mode"`
	Skipped          []SkippedDay     `json:"skipped"`
	BalanceYear      int              `json:"balance_year"`
	BalanceRule      string           `json:"balance_rule"`
	RemainingBalance *decimal.Decimal `json:"remaining_balance"`
	PendingDays      decimal.Decimal  `json:"pending_days"`
	AvailableBalance *decimal.Decimal `json:"available_balance"`
	Refused          bool             `json:"refused"`
	BalanceMessage   string           `json:"balance_message,omitempty"`
	StartHalfDay     bool             `json:"start_half_day"`
	EndHalfDay       bool             `json:"end_half_day"`

	category *ent.LeaveCategory
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

func modeOf(modes map[string]string, c *ent.LeaveCategory) string {
	if m := modes[c.ID.String()]; m == CountWorkingDays || m == CountCalendarDays {
		return m
	}
	return defaultCountMode(c.Name)
}

// CategoryViews adds the tenant's settings to leave types.
func (s *Service) CategoryViews(ctx context.Context, tenantID uuid.UUID, rows []*ent.LeaveCategory) ([]CategoryView, error) {
	modes, err := typeSettings(ctx, s.orm, tenantID, CountModesKey)
	if err != nil {
		return nil, err
	}
	rules, err := typeSettings(ctx, s.orm, tenantID, BalanceRulesKey)
	if err != nil {
		return nil, err
	}
	changes, err := typeOverrides(ctx, s.orm, tenantID)
	if err != nil {
		return nil, err
	}
	out := make([]CategoryView, len(rows))
	for i, c := range rows {
		inherited := c.TenantID != tenantID
		_, changed := changes[c.ID.String()]
		out[i] = CategoryView{LeaveCategory: c, IsActive: c.IsActive, CountMode: modeOf(modes, c), BalanceRule: ruleOf(rules, c),
			Inherited: inherited, Customised: inherited && changed}
	}
	return out, nil
}

// SetCountMode stores how the tenant counts one of the leave types it uses, including a platform
// type it inherits.
func (s *Service) SetCountMode(ctx context.Context, tenantID, categoryID uuid.UUID, mode string) (*CategoryView, error) {
	if mode != CountWorkingDays && mode != CountCalendarDays {
		return nil, ErrCountMode
	}
	return s.saveTypeSetting(ctx, tenantID, categoryID, CountModesKey, mode)
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

// PreviewRequest counts the days a request of full days would take and reports the dates it skips.
func (s *Service) PreviewRequest(ctx context.Context, tenantID, employeeID, categoryID uuid.UUID, start, end time.Time) (*Preview, error) {
	return s.PreviewRequestWith(ctx, tenantID, employeeID, categoryID, start, end, RequestOptions{})
}

// PreviewRequestWith counts the days a request would take, its half days included: a half counts
// half of that day under the type's count mode.
func (s *Service) PreviewRequestWith(ctx context.Context, tenantID, employeeID, categoryID uuid.UUID, start, end time.Time, o RequestOptions) (*Preview, error) {
	start, end = utcDay(start), utcDay(end)
	if end.Before(start) {
		return nil, ErrDateOrder
	}
	if start.Equal(end) && o.StartHalfDay && o.EndHalfDay {
		return nil, ErrBothHalves
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
	modes, err := typeSettings(ctx, s.orm, tenantID, CountModesKey)
	if err != nil {
		return nil, err
	}
	p := &Preview{category: cat, CountMode: modeOf(modes, cat), Skipped: []SkippedDay{}, BalanceYear: start.Year(),
		StartHalfDay: o.StartHalfDay, EndHalfDay: o.EndHalfDay}
	// share is what one day counts, its half included.
	share := func(day time.Time, full decimal.Decimal) decimal.Decimal {
		if (o.StartHalfDay && day.Equal(start)) || (o.EndHalfDay && day.Equal(end)) {
			return halfShare(full)
		}
		return full
	}
	if p.CountMode == CountCalendarDays {
		for d := start; !d.After(end); d = d.AddDate(0, 0, 1) {
			p.Days = p.Days.Add(share(d, decimal.NewFromInt(1)))
		}
	} else {
		if s.calendar == nil {
			return nil, ErrNoCalendar
		}
		days, err := s.calendar.PlannedDays(ctx, tenantID, employeeID, start, end)
		if err != nil {
			return nil, err
		}
		for _, d := range days {
			p.Days = p.Days.Add(share(utcDay(d.Date), d.Share))
			if d.Reason != "" {
				p.Skipped = append(p.Skipped, SkippedDay{Date: d.Date.Format("2006-01-02"), Reason: d.Reason, Name: d.Name, Share: d.Share})
			}
		}
	}
	chk, err := s.checkBalanceExcluding(ctx, s.orm, tenantID, employeeID, cat, p.BalanceYear, p.Days, true, o.Excluding)
	if err != nil {
		return nil, err
	}
	p.BalanceRule, p.RemainingBalance, p.PendingDays, p.AvailableBalance = chk.Rule, chk.Remaining, chk.Pending, chk.Available
	p.Refused, p.BalanceMessage = chk.refusal() != nil, chk.Message
	return p, nil
}

// refuseOverlap rejects dates that touch another pending or approved request of the employee
// (o.Excluding, the request being edited, aside). The morning of a day and its afternoon may be
// two requests.
func refuseOverlap(ctx context.Context, tx *ent.Tx, tenantID, employeeID uuid.UUID, start, end time.Time, o RequestOptions) error {
	q := tx.LeaveRequest.Query().Where(
		leaverequest.TenantID(tenantID), leaverequest.EmployeeID(employeeID),
		leaverequest.StatusIn(leaverequest.StatusPending, leaverequest.StatusApproved),
		leaverequest.StartDateLT(end.AddDate(0, 0, 1)), leaverequest.EndDateGTE(start),
	)
	if o.Excluding != uuid.Nil {
		q = q.Where(leaverequest.IDNEQ(o.Excluding))
	}
	rows, err := q.All(ctx)
	if err != nil {
		return fmt.Errorf("leave: check overlap: %w", err)
	}
	for _, row := range rows {
		if splitDay(row, start, end, o) {
			continue
		}
		return fmt.Errorf("these dates overlap %s leave from %s to %s", row.Status,
			row.StartDate.Format("2006-01-02"), row.EndDate.Format("2006-01-02"))
	}
	return nil
}

// splitDay tells whether an existing request and new dates share only one day, one of them
// taking its morning and the other its afternoon.
func splitDay(row *ent.LeaveRequest, start, end time.Time, o RequestOptions) bool {
	rs, re := utcDay(row.StartDate), utcDay(row.EndDate)
	from, to := rs, re
	if start.After(from) {
		from = start
	}
	if end.Before(to) {
		to = end
	}
	if !from.Equal(to) {
		return false
	}
	day := from
	// The morning only: the leave ends at midday that day. The afternoon only: it starts then.
	rowMorning, rowAfternoon := re.Equal(day) && row.EndHalfDay, rs.Equal(day) && row.StartHalfDay
	newMorning, newAfternoon := end.Equal(day) && o.EndHalfDay, start.Equal(day) && o.StartHalfDay
	return (rowMorning && newAfternoon) || (rowAfternoon && newMorning)
}
