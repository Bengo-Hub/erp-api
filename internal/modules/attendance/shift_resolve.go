package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftassignment"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftroster"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftrosterslot"
	"github.com/Bengo-Hub/erp-api/internal/ent/staffshiftoverride"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshiftschedule"
)

// Shift sources, in the order they win.
const (
	ShiftFromOverride = "override"
	ShiftFromRoster   = "roster"
	ShiftFromEmployee = "employee"
	ShiftFromDefault  = "default"
	ShiftFromNone     = "none"
)

// DayShift is the shift an employee is planned to work on one day.
type DayShift struct {
	ShiftID  *uuid.UUID `json:"work_shift_id,omitempty"`
	Name     string     `json:"name,omitempty"`
	Start    string     `json:"start_time,omitempty"` // HH:MM local
	End      string     `json:"end_time,omitempty"`   // HH:MM local; not after Start = ends next day
	Grace    int        `json:"grace_minutes"`
	Off      bool       `json:"off"` // planned day off
	Source   string     `json:"source"`
	OutletID *uuid.UUID `json:"-"` // the shift's outlet, for its zone
	HalfDay  bool       `json:"-"` // a half-day override
}

// Overnight reports whether the shift ends on the day after it starts.
func (d DayShift) Overnight() bool {
	return d.Start != "" && d.End != "" && d.End <= d.Start
}

// empDay keys an employee's work day (date as UTC midnight).
type empDay struct {
	Emp uuid.UUID
	Day time.Time
}

// resolveShifts answers the planned shift for every (employee, day) in a fixed number of
// queries: an approved staff shift override wins, then the roster slot of the employee's
// active roster assignment, then the employee's standard work shift, then the tenant default.
func (s *Service) resolveShifts(ctx context.Context, tenantID uuid.UUID, keys []empDay, st Settings) (map[empDay]DayShift, error) {
	out := make(map[empDay]DayShift, len(keys))
	if len(keys) == 0 {
		return out, nil
	}
	empSet := map[uuid.UUID]bool{}
	lo, hi := keys[0].Day, keys[0].Day
	for _, k := range keys {
		empSet[k.Emp] = true
		if k.Day.Before(lo) {
			lo = k.Day
		}
		if k.Day.After(hi) {
			hi = k.Day
		}
	}
	empIDs := make([]uuid.UUID, 0, len(empSet))
	for id := range empSet {
		empIDs = append(empIDs, id)
	}

	overrides, err := s.orm.StaffShiftOverride.Query().Where(
		staffshiftoverride.TenantID(tenantID),
		staffshiftoverride.EmployeeIDIn(empIDs...),
		staffshiftoverride.StatusEQ(staffshiftoverride.StatusApproved),
		staffshiftoverride.DateGTE(lo), staffshiftoverride.DateLT(hi.AddDate(0, 0, 1)),
	).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: resolve overrides: %w", err)
	}
	ovr := map[empDay]*ent.StaffShiftOverride{}
	for _, o := range overrides {
		ovr[empDay{o.EmployeeID, dateOnly(o.Date)}] = o
	}

	assigns, err := s.orm.ShiftAssignment.Query().Where(
		shiftassignment.TenantID(tenantID),
		shiftassignment.EmployeeIDIn(empIDs...),
		shiftassignment.IsActive(true),
		shiftassignment.StartDateLT(hi.AddDate(0, 0, 1)),
		shiftassignment.Or(shiftassignment.EndDateIsNil(), shiftassignment.EndDateGTE(lo)),
	).Order(ent.Desc(shiftassignment.FieldStartDate)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: resolve assignments: %w", err)
	}
	byEmpAssign := map[uuid.UUID][]*ent.ShiftAssignment{}
	rosterIDs := []uuid.UUID{}
	for _, a := range assigns {
		byEmpAssign[a.EmployeeID] = append(byEmpAssign[a.EmployeeID], a)
		rosterIDs = append(rosterIDs, a.RosterID)
	}
	rosters := map[uuid.UUID]*ent.ShiftRoster{}
	type slotKey struct {
		roster, emp uuid.UUID
		day         int
	}
	slots := map[slotKey]*ent.ShiftRosterSlot{}
	if len(rosterIDs) > 0 {
		rows, err := s.orm.ShiftRoster.Query().Where(
			shiftroster.TenantID(tenantID), shiftroster.IDIn(rosterIDs...), shiftroster.IsActive(true)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: resolve rosters: %w", err)
		}
		for _, r := range rows {
			rosters[r.ID] = r
		}
		srows, err := s.orm.ShiftRosterSlot.Query().Where(
			shiftrosterslot.TenantID(tenantID), shiftrosterslot.RosterIDIn(rosterIDs...),
			shiftrosterslot.EmployeeIDIn(empIDs...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: resolve roster slots: %w", err)
		}
		for _, sl := range srows {
			slots[slotKey{sl.RosterID, sl.EmployeeID, sl.CycleDay}] = sl
		}
	}

	emps, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.IDIn(empIDs...)).
		Select(employee.FieldID, employee.FieldWorkShiftID, employee.FieldOutletID).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: resolve employees: %w", err)
	}
	empShift := map[uuid.UUID]uuid.UUID{}
	shiftIDs := map[uuid.UUID]bool{}
	for _, e := range emps {
		if e.WorkShiftID != nil {
			empShift[e.ID] = *e.WorkShiftID
			shiftIDs[*e.WorkShiftID] = true
		}
	}
	for _, o := range overrides {
		if o.WorkShiftID != nil {
			shiftIDs[*o.WorkShiftID] = true
		}
	}
	ids := make([]uuid.UUID, 0, len(shiftIDs))
	for id := range shiftIDs {
		ids = append(ids, id)
	}
	shifts, err := s.orm.WorkShift.Query().Where(workshift.TenantID(tenantID),
		workshift.Or(workshift.IDIn(ids...), workshift.IsDefault(true))).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: resolve shifts: %w", err)
	}
	cat := newShiftCatalog(shifts)
	if len(shifts) > 0 {
		all := make([]uuid.UUID, 0, len(shifts))
		for _, sh := range shifts {
			all = append(all, sh.ID)
		}
		scheds, err := s.orm.WorkShiftSchedule.Query().Where(
			workshiftschedule.TenantID(tenantID), workshiftschedule.WorkShiftIDIn(all...)).All(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: resolve schedules: %w", err)
		}
		cat.addSchedules(scheds)
	}

	for _, k := range keys {
		out[k] = resolveOne(k, ovr[k], byEmpAssign[k.Emp], func(a *ent.ShiftAssignment) (*ent.ShiftRosterSlot, bool) {
			r := rosters[a.RosterID]
			if r == nil || r.CycleDays <= 0 {
				return nil, false
			}
			cd := cycleDay(k.Day, dateOnly(r.StartDate), r.CycleDays)
			sl, ok := slots[slotKey{r.ID, k.Emp, cd}]
			return sl, ok
		}, empShift, cat, st)
	}
	return out, nil
}

// cycleDay is the 1-based position of day within a roster cycle anchored at start.
func cycleDay(day, start time.Time, cycleDays int) int {
	diff := int(day.Sub(start).Hours() / 24)
	m := diff % cycleDays
	if m < 0 {
		m += cycleDays
	}
	return m + 1
}

// resolveOne applies the precedence for one employee day.
func resolveOne(k empDay, o *ent.StaffShiftOverride, assigns []*ent.ShiftAssignment,
	slotFor func(*ent.ShiftAssignment) (*ent.ShiftRosterSlot, bool),
	empShift map[uuid.UUID]uuid.UUID, cat *shiftCatalog, st Settings) DayShift {
	base := cat.forEmployee(k.Emp, empShift)
	if o != nil {
		ds := DayShift{Source: ShiftFromOverride, Grace: base.Grace, OutletID: o.OutletID}
		if o.OverrideType == staffshiftoverride.OverrideTypeOffDuty {
			ds.Off = true
			return ds
		}
		if o.WorkShiftID != nil {
			if sh := cat.day(*o.WorkShiftID, k.Day, st); sh.ShiftID != nil {
				ds = sh
				ds.Source = ShiftFromOverride
				ds.Off = false
			}
		}
		if o.StartTime != nil && o.EndTime != nil {
			ds.Start, ds.End = *o.StartTime, *o.EndTime
		}
		ds.HalfDay = o.OverrideType == staffshiftoverride.OverrideTypeHalfDay
		return ds
	}
	for _, a := range assigns {
		if dateOnly(a.StartDate).After(k.Day) || (a.EndDate != nil && dateOnly(*a.EndDate).Before(k.Day)) {
			continue
		}
		sl, ok := slotFor(a)
		if !ok {
			break // assigned to a roster with no slot for this day: fall back to the standard shift
		}
		ds := DayShift{Source: ShiftFromRoster, Grace: base.Grace, Off: sl.IsOffDay, OutletID: base.OutletID}
		if sl.StartTime != nil && sl.EndTime != nil {
			ds.Start, ds.End = *sl.StartTime, *sl.EndTime
		}
		return ds
	}
	if id, ok := empShift[k.Emp]; ok {
		if ds := cat.day(id, k.Day, st); ds.ShiftID != nil {
			ds.Source = ShiftFromEmployee
			return ds
		}
	}
	if cat.def != nil {
		ds := cat.day(cat.def.ID, k.Day, st)
		ds.Source = ShiftFromDefault
		return ds
	}
	return DayShift{Source: ShiftFromNone}
}

// shiftCatalog holds work shifts and their per-day schedules for resolution.
type shiftCatalog struct {
	shifts map[uuid.UUID]*ent.WorkShift
	sched  map[uuid.UUID]map[string]*ent.WorkShiftSchedule
	def    *ent.WorkShift
}

func newShiftCatalog(shifts []*ent.WorkShift) *shiftCatalog {
	c := &shiftCatalog{shifts: map[uuid.UUID]*ent.WorkShift{}, sched: map[uuid.UUID]map[string]*ent.WorkShiftSchedule{}}
	for _, sh := range shifts {
		c.shifts[sh.ID] = sh
		if sh.IsDefault && c.def == nil {
			c.def = sh
		}
	}
	return c
}

func (c *shiftCatalog) addSchedules(rows []*ent.WorkShiftSchedule) {
	for _, r := range rows {
		m := c.sched[r.WorkShiftID]
		if m == nil {
			m = map[string]*ent.WorkShiftSchedule{}
			c.sched[r.WorkShiftID] = m
		}
		m[string(r.Day)] = r
	}
}

// forEmployee is the employee's standard shift (else the default) for its grace and outlet.
func (c *shiftCatalog) forEmployee(emp uuid.UUID, empShift map[uuid.UUID]uuid.UUID) DayShift {
	sh := c.def
	if id, ok := empShift[emp]; ok && c.shifts[id] != nil {
		sh = c.shifts[id]
	}
	if sh == nil {
		return DayShift{}
	}
	return DayShift{Grace: sh.GraceMinutes, OutletID: sh.OutletID}
}

// day is a shift's plan for one date: its schedule row for the weekday, else its legacy
// times on the tenant's default working days. A shift with schedule rows but none for the
// weekday, or a non-working row, is a day off.
func (c *shiftCatalog) day(shiftID uuid.UUID, d time.Time, st Settings) DayShift {
	sh := c.shifts[shiftID]
	if sh == nil {
		return DayShift{}
	}
	id := sh.ID
	ds := DayShift{ShiftID: &id, Name: sh.Name, Grace: sh.GraceMinutes, OutletID: sh.OutletID}
	weekday := scheduleDayFor(d)
	if rows, ok := c.sched[sh.ID]; ok && len(rows) > 0 {
		r, ok := rows[weekday]
		if !ok || !r.IsWorkingDay {
			ds.Off = true
			return ds
		}
		ds.Start, ds.End = r.StartTime, r.EndTime
		return ds
	}
	if sh.StartTime != nil {
		ds.Start = *sh.StartTime
	}
	if sh.EndTime != nil {
		ds.End = *sh.EndTime
	}
	ds.Off = !containsDay(st.DefaultWorkingDays, weekday)
	return ds
}

func containsDay(days []string, d string) bool {
	for _, x := range days {
		if x == d {
			return true
		}
	}
	return false
}
