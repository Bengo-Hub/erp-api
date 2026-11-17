package attendance

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/customuser"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/leaverequest"
	"github.com/Bengo-Hub/erp-api/internal/ent/publicholiday"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshiftschedule"
)

// Capacity (owner, 17 November 2026): a person's working hours per ISO week for projects-api's
// workload. The weekly hours come from the employee's standard work shift (employees.work_shift_id):
// its total_hours_per_week spread evenly over its working days, or, when that is zero, the hours of
// its working-day schedule (end minus start minus break). Without a schedule the working days are
// Monday to Friday. Approved leave and national public holidays on a working day take that day's
// hours off; a day that is both counts once. A leave request whose days_requested is less than its
// working days (a half day) takes off that share of each day.
//
// The read is batched: at most six queries whatever the number of people (users, employees, shifts,
// their schedules, approved leave, holidays), never one per person.

const (
	// MaxCapacityUsers caps one capacity read (projects-api shows at most 500 people).
	MaxCapacityUsers = 500
	// MaxCapacityDays caps the date range of one read (projects-api asks for at most 26 weeks).
	MaxCapacityDays = 366
)

// ErrCapacityRange is a from/to the capacity read refuses.
var ErrCapacityRange = errors.New("attendance: capacity range must have from on or before to and span at most 366 days")

// CapacityWeek is one ISO week of a person's capacity. Hours is the shift's weekly hours minus
// LeaveHours and HolidayHours.
type CapacityWeek struct {
	WeekStart    string          `json:"week_start"`
	Hours        decimal.Decimal `json:"hours"`
	LeaveHours   decimal.Decimal `json:"leave_hours"`
	HolidayHours decimal.Decimal `json:"holiday_hours"`
}

// PersonCapacity is one auth user's capacity. HasEmployee says ERP has an active employee for the
// user; Configured says that employee has a standard work shift with hours, and only then are
// WeeklyHours and Weeks filled (a caller falls back to its own setting otherwise).
type PersonCapacity struct {
	AuthUserID  string          `json:"auth_user_id"`
	HasEmployee bool            `json:"has_employee"`
	Configured  bool            `json:"configured"`
	WorkShift   string          `json:"work_shift,omitempty"`
	WeeklyHours decimal.Decimal `json:"weekly_hours"`
	Weeks       []CapacityWeek  `json:"weeks"`
}

// mondayOf is the Monday (UTC midnight) of t's ISO week.
func mondayOf(t time.Time) time.Time {
	y, m, d := t.UTC().Date()
	day := time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
	return day.AddDate(0, 0, -((int(day.Weekday()) + 6) % 7))
}

func dateOnly(t time.Time) time.Time {
	y, m, d := t.UTC().Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

// shiftWeek is a shift's hours per weekday (0 = Sunday, as time.Weekday).
type shiftWeek struct {
	name  string
	daily [7]decimal.Decimal
}

func (w shiftWeek) total() decimal.Decimal {
	sum := decimal.Zero
	for _, h := range w.daily {
		sum = sum.Add(h)
	}
	return sum
}

// clockHours is end minus start of an HH:MM pair, past midnight when end is earlier; ok is false
// when either does not parse.
func clockHours(start, end string) (decimal.Decimal, bool) {
	s, err1 := time.Parse("15:04", strings.TrimSpace(start))
	e, err2 := time.Parse("15:04", strings.TrimSpace(end))
	if err1 != nil || err2 != nil {
		return decimal.Zero, false
	}
	d := e.Sub(s)
	if d <= 0 {
		d += 24 * time.Hour
	}
	return decimal.NewFromFloat(d.Hours()), true
}

// weekOfShift turns a shift and its schedule rows into hours per weekday. ok is false when the
// shift gives no hours at all (no weekly total and no usable schedule).
func weekOfShift(ws *ent.WorkShift, rows []*ent.WorkShiftSchedule) (shiftWeek, bool) {
	out := shiftWeek{name: ws.Name}
	var working [7]bool
	var scheduled [7]decimal.Decimal
	hasSchedule := false
	for _, r := range rows {
		wd, ok := weekdayByName[string(r.Day)]
		if !ok {
			continue
		}
		hasSchedule = true
		if !r.IsWorkingDay {
			continue
		}
		working[wd] = true
		if h, ok := clockHours(r.StartTime, r.EndTime); ok {
			h = h.Sub(r.BreakHours)
			if h.IsPositive() {
				scheduled[wd] = h
			}
		}
	}
	if !hasSchedule {
		for wd := time.Monday; wd <= time.Friday; wd++ {
			working[wd] = true
		}
	}
	if ws.TotalHoursPerWeek.IsPositive() {
		n := 0
		for _, w := range working {
			if w {
				n++
			}
		}
		if n == 0 {
			return out, false
		}
		per := ws.TotalHoursPerWeek.Div(decimal.NewFromInt(int64(n)))
		for wd, w := range working {
			if w {
				out.daily[wd] = per
			}
		}
		return out, true
	}
	out.daily = scheduled
	return out, out.total().IsPositive()
}

var weekdayByName = map[string]time.Weekday{
	"Sunday": time.Sunday, "Monday": time.Monday, "Tuesday": time.Tuesday, "Wednesday": time.Wednesday,
	"Thursday": time.Thursday, "Friday": time.Friday, "Saturday": time.Saturday,
}

// leaveSpan is one approved leave request: its own date range and the share of each working day
// in it that it takes off.
type leaveSpan struct {
	from, to time.Time
	share    decimal.Decimal
}

// Capacity answers each auth user's capacity per ISO week, for every week from the Monday of from
// to the week holding to (whole weeks). Users come back in the order asked; an id ERP does not
// know comes back with HasEmployee false.
func (s *Service) Capacity(ctx context.Context, tenantID uuid.UUID, authUserIDs []string, from, to time.Time) ([]PersonCapacity, error) {
	from, to = dateOnly(from), dateOnly(to)
	if to.Before(from) || to.Sub(from) > MaxCapacityDays*24*time.Hour {
		return nil, ErrCapacityRange
	}
	if len(authUserIDs) > MaxCapacityUsers {
		return nil, fmt.Errorf("attendance: at most %d users per capacity read", MaxCapacityUsers)
	}
	start := mondayOf(from)
	end := mondayOf(to).AddDate(0, 0, 6)
	out := make([]PersonCapacity, len(authUserIDs))
	if len(authUserIDs) == 0 {
		return out, nil
	}
	keys := make([]string, len(authUserIDs))
	for i, id := range authUserIDs {
		keys[i] = strings.ToLower(strings.TrimSpace(id))
		out[i] = PersonCapacity{AuthUserID: keys[i], WeeklyHours: decimal.Zero, Weeks: []CapacityWeek{}}
	}

	// 1. Users and their employees (the oldest live employee of the tenant per user, as the
	// for-user timesheet routes resolve it).
	users, err := s.orm.CustomUser.Query().Where(customuser.ExternalIDIn(keys...)).
		Select(customuser.FieldID, customuser.FieldExternalID).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: capacity users: %w", err)
	}
	userKey := make(map[uuid.UUID]string, len(users))
	userIDs := make([]uuid.UUID, 0, len(users))
	for _, u := range users {
		userKey[u.ID] = strings.ToLower(u.ExternalID)
		userIDs = append(userIDs, u.ID)
	}
	empByKey := map[string]*ent.Employee{}
	if len(userIDs) > 0 {
		emps, err := s.orm.Employee.Query().
			Where(employee.TenantID(tenantID), employee.UserIDIn(userIDs...), employee.Deleted(false), employee.Terminated(false)).
			Order(ent.Asc(employee.FieldCreatedAt), ent.Asc(employee.FieldID)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: capacity employees: %w", err)
		}
		for _, e := range emps {
			if e.UserID == nil {
				continue
			}
			if k, ok := userKey[*e.UserID]; ok {
				if _, seen := empByKey[k]; !seen {
					empByKey[k] = e
				}
			}
		}
	}

	// 2. Their shifts and the shifts' schedules.
	shiftIDs := map[uuid.UUID]bool{}
	for _, e := range empByKey {
		if e.WorkShiftID != nil {
			shiftIDs[*e.WorkShiftID] = true
		}
	}
	weeks := map[uuid.UUID]shiftWeek{}
	if len(shiftIDs) > 0 {
		ids := make([]uuid.UUID, 0, len(shiftIDs))
		for id := range shiftIDs {
			ids = append(ids, id)
		}
		shifts, err := s.orm.WorkShift.Query().Where(workshift.TenantID(tenantID), workshift.IDIn(ids...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: capacity shifts: %w", err)
		}
		sched, err := s.orm.WorkShiftSchedule.Query().
			Where(workshiftschedule.TenantID(tenantID), workshiftschedule.WorkShiftIDIn(ids...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: capacity schedules: %w", err)
		}
		byShift := map[uuid.UUID][]*ent.WorkShiftSchedule{}
		for _, r := range sched {
			byShift[r.WorkShiftID] = append(byShift[r.WorkShiftID], r)
		}
		for _, ws := range shifts {
			if w, ok := weekOfShift(ws, byShift[ws.ID]); ok {
				weeks[ws.ID] = w
			}
		}
	}

	// 3. Approved leave of the configured employees overlapping the weeks.
	configured := map[uuid.UUID]shiftWeek{}
	for _, e := range empByKey {
		if e.WorkShiftID == nil {
			continue
		}
		if w, ok := weeks[*e.WorkShiftID]; ok {
			configured[e.ID] = w
		}
	}
	leave := map[uuid.UUID][]*ent.LeaveRequest{}
	lo, hi := start, end
	if len(configured) > 0 {
		empIDs := make([]uuid.UUID, 0, len(configured))
		for id := range configured {
			empIDs = append(empIDs, id)
		}
		rows, err := s.orm.LeaveRequest.Query().
			Where(leaverequest.TenantID(tenantID), leaverequest.EmployeeIDIn(empIDs...),
				leaverequest.StatusEQ(leaverequest.StatusApproved),
				leaverequest.StartDateLTE(end.AddDate(0, 0, 1)), leaverequest.EndDateGTE(start)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: capacity leave: %w", err)
		}
		for _, r := range rows {
			leave[r.EmployeeID] = append(leave[r.EmployeeID], r)
			if d := dateOnly(r.StartDate); d.Before(lo) {
				lo = d
			}
			if d := dateOnly(r.EndDate); d.After(hi) {
				hi = d
			}
		}
	}

	// 4. National public holidays over the weeks and the leave requests' own ranges.
	holidays := map[time.Time]bool{}
	if len(configured) > 0 {
		rows, err := s.orm.PublicHoliday.Query().
			Where(publicholiday.TenantID(tenantID), publicholiday.IsNational(true),
				publicholiday.DateGTE(lo), publicholiday.DateLT(hi.AddDate(0, 0, 1))).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: capacity holidays: %w", err)
		}
		for _, h := range rows {
			holidays[dateOnly(h.Date)] = true
		}
	}

	for i, key := range keys {
		e, ok := empByKey[key]
		if !ok {
			continue
		}
		out[i].HasEmployee = true
		w, ok := configured[e.ID]
		if !ok {
			continue
		}
		out[i].Configured = true
		out[i].WorkShift = w.name
		out[i].WeeklyHours = w.total().Round(2)
		out[i].Weeks = capacityWeeks(w, start, end, leaveSpans(w, leave[e.ID], holidays), holidays)
	}
	return out, nil
}

// leaveSpans turns approved leave requests into date spans with the share of a working day each
// takes off: days_requested over the request's working days (holidays excluded), at most 1.
func leaveSpans(w shiftWeek, rows []*ent.LeaveRequest, holidays map[time.Time]bool) []leaveSpan {
	out := make([]leaveSpan, 0, len(rows))
	for _, r := range rows {
		span := leaveSpan{from: dateOnly(r.StartDate), to: dateOnly(r.EndDate), share: decimal.NewFromInt(1)}
		if span.to.Before(span.from) {
			continue
		}
		working := 0
		for d := span.from; !d.After(span.to); d = d.AddDate(0, 0, 1) {
			if w.daily[d.Weekday()].IsPositive() && !holidays[d] {
				working++
			}
		}
		if working > 0 && r.DaysRequested.IsPositive() {
			if share := r.DaysRequested.Div(decimal.NewFromInt(int64(working))); share.LessThan(span.share) {
				span.share = share
			}
		}
		out = append(out, span)
	}
	sort.Slice(out, func(a, b int) bool { return out[a].from.Before(out[b].from) })
	return out
}

// capacityWeeks walks every day of [start, end] (whole ISO weeks): a holiday on a working day takes
// the day's hours off, else the largest leave share covering the day does.
func capacityWeeks(w shiftWeek, start, end time.Time, spans []leaveSpan, holidays map[time.Time]bool) []CapacityWeek {
	weekly := w.total()
	var out []CapacityWeek
	for ws := start; !ws.After(end); ws = ws.AddDate(0, 0, 7) {
		cw := CapacityWeek{WeekStart: ws.Format(time.DateOnly), LeaveHours: decimal.Zero, HolidayHours: decimal.Zero}
		for i := 0; i < 7; i++ {
			d := ws.AddDate(0, 0, i)
			h := w.daily[d.Weekday()]
			if !h.IsPositive() {
				continue
			}
			if holidays[d] {
				cw.HolidayHours = cw.HolidayHours.Add(h)
				continue
			}
			share := decimal.Zero
			for _, sp := range spans {
				if !d.Before(sp.from) && !d.After(sp.to) && sp.share.GreaterThan(share) {
					share = sp.share
				}
			}
			cw.LeaveHours = cw.LeaveHours.Add(h.Mul(share))
		}
		cw.LeaveHours, cw.HolidayHours = cw.LeaveHours.Round(2), cw.HolidayHours.Round(2)
		cw.Hours = weekly.Sub(cw.LeaveHours).Sub(cw.HolidayHours).Round(2)
		if cw.Hours.IsNegative() {
			cw.Hours = decimal.Zero
		}
		out = append(out, cw)
	}
	return out
}
