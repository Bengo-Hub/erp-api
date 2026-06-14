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
	defaultOTThreshold   = decimal.NewFromInt(8)
	defaultMaxOvertime   = decimal.NewFromInt(4)
	defaultMinWorkHours  = decimal.NewFromInt(6)
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
	Rule               *ent.AttendanceRule // highest-priority active overtime_policy rule (may be nil)
	CurrentStatus      string
}

// computeHoursResult is the computed split + possibly-adjusted status.
type computeHoursResult struct {
	RegularHours  decimal.Decimal
	OvertimeHours decimal.Decimal
	Status        string
}

// computeHours splits worked time into regular vs overtime per the overtime AttendanceRule
// and flags half-day when worked hours fall below the rule minimum (port of
// AttendanceRecord.compute_hours). Pure: no DB access, no float.
func computeHours(in computeHoursInput) computeHoursResult {
	worked := decimal.NewFromInt(int64(in.TotalSecondsWorked)).Div(secondsPerHour)

	threshold := defaultOTThreshold
	maxOT := defaultMaxOvertime
	minHours := defaultMinWorkHours
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
	if in.HasCheckOut && worked.LessThan(minHours) {
		res.Status = "half-day"
	}
	return res
}

// isLate reports whether a check-in is past the effective shift start + grace minutes
// (port of AttendanceRecord.apply_late_status). startTime is "HH:MM"; empty disables the
// check. graceMinutes is the shift's grace window.
func isLate(checkIn time.Time, startTime string, graceMinutes int) bool {
	if startTime == "" {
		return false
	}
	t, err := time.Parse("15:04", startTime)
	if err != nil {
		return false
	}
	loc := checkIn.Location()
	expected := time.Date(checkIn.Year(), checkIn.Month(), checkIn.Day(), t.Hour(), t.Minute(), 0, 0, loc).
		Add(time.Duration(graceMinutes) * time.Minute)
	return checkIn.After(expected)
}

// scheduleDayFor maps a date to the WorkShiftSchedule day enum string.
func scheduleDayFor(d time.Time) string {
	return weekdayToScheduleDay[d.Weekday()]
}
