// Package attendance implements tenant-isolated attendance: shifts, schedules, records
// (with late-detection + overtime computation), rules, rotations, off-days, per-tenant ESS
// settings, timesheets, and the shift-planner roster (rosters/slots/assignments/overrides).
package attendance

import (
	"time"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

var (
	secondsPerHour       = decimal.NewFromInt(3600)
	twoDecimalPlaces     = int32(2)
	weekdayToScheduleDay = map[time.Weekday]string{
		time.Monday:    "Monday",
		time.Tuesday:   "Tuesday",
		time.Wednesday: "Wednesday",
		time.Thursday:  "Thursday",
		time.Friday:    "Friday",
		time.Saturday:  "Saturday",
		time.Sunday:    "Sunday",
	}
)

// computeHoursInput carries the inputs for splitting worked time into regular/overtime.
type computeHoursInput struct {
	TotalSecondsWorked int
	HasCheckOut        bool
	Rule               *ent.AttendanceRule // most specific active overtime_policy rule (may be nil)
	Settings           Settings            // tenant fallbacks when the rule leaves a value unset
	CurrentStatus      string
}

// computeHoursResult is the computed split + possibly-adjusted status.
type computeHoursResult struct {
	RegularHours  decimal.Decimal
	OvertimeHours decimal.Decimal
	Status        string
}

// computeHours splits worked time into regular vs overtime per the overtime AttendanceRule
// (else the tenant settings) and flags half-day when worked hours fall below the minimum.
// Pure: no DB access, no float.
func computeHours(in computeHoursInput) computeHoursResult {
	worked := decimal.NewFromInt(int64(in.TotalSecondsWorked)).Div(secondsPerHour)

	threshold := in.Settings.OTThresholdHours
	maxOT := in.Settings.OTMaxHours
	minHours := in.Settings.MinWorkHours
	if in.Rule != nil {
		if in.Rule.OvertimeThresholdHours.GreaterThan(decimal.Zero) {
			threshold = in.Rule.OvertimeThresholdHours
		}
		if in.Rule.MaxOvertimeHours.GreaterThan(decimal.Zero) {
			maxOT = in.Rule.MaxOvertimeHours
		}
		if in.Rule.MinWorkHours.GreaterThan(decimal.Zero) {
			minHours = in.Rule.MinWorkHours
		}
	}
	if !threshold.IsPositive() {
		// No threshold anywhere means no overtime split at all.
		threshold = worked
	}

	overtime := worked.Sub(threshold)
	if overtime.LessThan(decimal.Zero) {
		overtime = decimal.Zero
	}
	if overtime.GreaterThan(maxOT) {
		overtime = maxOT
	}
	regular := worked.Sub(overtime)

	res := computeHoursResult{
		RegularHours:  regular.Round(twoDecimalPlaces),
		OvertimeHours: overtime.Round(twoDecimalPlaces),
		Status:        in.CurrentStatus,
	}
	if in.HasCheckOut && minHours.IsPositive() && worked.LessThan(minHours) {
		res.Status = "half-day"
	}
	return res
}

// clockOn returns the wall-clock time hhmm on workDate's calendar day in loc. workDate is
// read by its UTC calendar date (records store the day as UTC midnight).
func clockOn(workDate time.Time, hhmm string, loc *time.Location) (time.Time, bool) {
	t, err := time.Parse("15:04", hhmm)
	if err != nil {
		return time.Time{}, false
	}
	y, m, d := workDate.UTC().Date()
	return time.Date(y, m, d, t.Hour(), t.Minute(), 0, 0, loc), true
}

// shiftWindow returns the shift's start and end instants for workDate. A shift whose end is
// not after its start (22:00 to 06:00) is a night shift and ends on the next day.
func shiftWindow(workDate time.Time, start, end string, loc *time.Location) (from, to time.Time, ok bool) {
	from, ok = clockOn(workDate, start, loc)
	if !ok {
		return time.Time{}, time.Time{}, false
	}
	to, ok = clockOn(workDate, end, loc)
	if !ok {
		return time.Time{}, time.Time{}, false
	}
	if !to.After(from) {
		to = to.Add(24 * time.Hour)
	}
	return from, to, true
}

// lateMinutesAt is how many minutes after the shift start on workDate the check-in fell, when
// it fell after the grace window, else 0. Lateness counts from the start, not from the end of
// the grace, because the grace only decides whether an arrival counts as late. The start is
// local wall-clock time in loc, so a UTC check-in is compared correctly.
func lateMinutesAt(checkIn, workDate time.Time, startTime string, graceMinutes int, loc *time.Location) int {
	if startTime == "" || loc == nil {
		return 0
	}
	start, ok := clockOn(workDate, startTime, loc)
	if !ok {
		return 0
	}
	if !checkIn.After(start.Add(time.Duration(graceMinutes) * time.Minute)) {
		return 0
	}
	return int(checkIn.Sub(start).Minutes())
}

// isLate reports whether a check-in is past the shift start + grace minutes on the check-in's
// own local day in loc (port of AttendanceRecord.apply_late_status).
func isLate(checkIn time.Time, loc *time.Location, startTime string, graceMinutes int) bool {
	if loc == nil {
		loc = time.UTC
	}
	return lateMinutesAt(checkIn, localDate(checkIn, loc), startTime, graceMinutes, loc) > 0
}

// earlyLeaveMinutes is how many minutes before the shift end the check-out happened, when it
// was earlier than the end minus the grace, else 0. Night shifts end on the next day.
func earlyLeaveMinutes(checkOut, workDate time.Time, startTime, endTime string, graceMinutes int, loc *time.Location) int {
	if startTime == "" || endTime == "" || loc == nil {
		return 0
	}
	_, end, ok := shiftWindow(workDate, startTime, endTime, loc)
	if !ok {
		return 0
	}
	if !checkOut.Before(end.Add(-time.Duration(graceMinutes) * time.Minute)) {
		return 0
	}
	return int(end.Sub(checkOut).Minutes())
}

// localDate is t's calendar day in loc, as UTC midnight (the way records store a date).
func localDate(t time.Time, loc *time.Location) time.Time {
	y, m, d := t.In(loc).Date()
	return time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
}

// scheduleDayFor maps a date to the WorkShiftSchedule day enum string.
func scheduleDayFor(d time.Time) string {
	return weekdayToScheduleDay[d.Weekday()]
}
