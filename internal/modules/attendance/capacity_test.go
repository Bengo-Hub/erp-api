package attendance

import (
	"testing"
	"time"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshiftschedule"
)

func dec(s string) decimal.Decimal { return decimal.RequireFromString(s) }

func sched(d workshiftschedule.Day, start, end, brk string, working bool) *ent.WorkShiftSchedule {
	return &ent.WorkShiftSchedule{Day: d, StartTime: start, EndTime: end, BreakHours: dec(brk), IsWorkingDay: working}
}

// A weekly total spreads over the working days (Monday to Friday without a schedule, the
// schedule's working days with one); without a total the schedule's own hours count; a shift with
// neither gives no capacity.
func TestWeekOfShift(t *testing.T) {
	w, ok := weekOfShift(&ent.WorkShift{Name: "Office", TotalHoursPerWeek: dec("40")}, nil)
	if !ok || !w.total().Equal(dec("40")) || !w.daily[time.Monday].Equal(dec("8")) || !w.daily[time.Saturday].IsZero() {
		t.Fatalf("40 h Monday to Friday: %+v %v", w.daily, ok)
	}

	sixDays := []*ent.WorkShiftSchedule{
		sched(workshiftschedule.DayMonday, "08:00", "17:00", "1", true),
		sched(workshiftschedule.DayTuesday, "08:00", "17:00", "1", true),
		sched(workshiftschedule.DayWednesday, "08:00", "17:00", "1", true),
		sched(workshiftschedule.DayThursday, "08:00", "17:00", "1", true),
		sched(workshiftschedule.DayFriday, "08:00", "17:00", "1", true),
		sched(workshiftschedule.DaySaturday, "09:00", "13:00", "0", true),
		sched(workshiftschedule.DaySunday, "00:00", "00:00", "0", false),
	}
	w, ok = weekOfShift(&ent.WorkShift{Name: "Shop", TotalHoursPerWeek: dec("45")}, sixDays)
	if !ok || !w.daily[time.Saturday].Equal(dec("7.5")) || !w.daily[time.Sunday].IsZero() || !w.total().Equal(dec("45")) {
		t.Fatalf("45 h over six days: %+v", w.daily)
	}
	w, ok = weekOfShift(&ent.WorkShift{Name: "Shop"}, sixDays)
	if !ok || !w.total().Equal(dec("44")) || !w.daily[time.Saturday].Equal(dec("4")) {
		t.Fatalf("schedule hours: %+v total %s", w.daily, w.total())
	}
	night := []*ent.WorkShiftSchedule{sched(workshiftschedule.DayMonday, "22:00", "06:00", "0.5", true)}
	if w, _ = weekOfShift(&ent.WorkShift{Name: "Night"}, night); !w.daily[time.Monday].Equal(dec("7.5")) {
		t.Fatalf("overnight shift: %s", w.daily[time.Monday])
	}
	if _, ok = weekOfShift(&ent.WorkShift{Name: "Empty"}, nil); ok {
		t.Fatal("a shift with no total and no schedule has no capacity")
	}
}

// Leave and holidays come off the working days of each whole ISO week: a holiday on a working day
// takes the whole day, a day that is both leave and holiday counts once, a half-day request takes
// half the day, and weekends never count.
func TestCapacityWeeks(t *testing.T) {
	w, _ := weekOfShift(&ent.WorkShift{Name: "Office", TotalHoursPerWeek: dec("40")}, nil)
	holidays := map[time.Time]bool{day("2026-12-01"): true, day("2026-12-12"): true} // a Tuesday and a Saturday
	leave := []*ent.LeaveRequest{
		{StartDate: day("2026-11-30"), EndDate: day("2026-12-02"), DaysRequested: dec("2")}, // Mon-Wed around the Tuesday holiday
		{StartDate: day("2026-12-07"), EndDate: day("2026-12-07"), DaysRequested: dec("0.5")},
		{StartDate: day("2026-12-19"), EndDate: day("2026-12-20"), DaysRequested: dec("0")}, // a weekend: nothing to take off
	}
	spans := leaveSpans(w, leave, holidays)
	// Pending leave: the Monday half day already approved leaves half the day free, so a pending
	// full day there counts 4 h; a pending day on the holiday counts nothing; a pending Thursday 8 h.
	pendingLeave := []*ent.LeaveRequest{
		{StartDate: day("2026-12-07"), EndDate: day("2026-12-07"), DaysRequested: dec("1")},
		{StartDate: day("2026-12-01"), EndDate: day("2026-12-01"), DaysRequested: dec("1")},
		{StartDate: day("2026-12-17"), EndDate: day("2026-12-17"), DaysRequested: dec("1")},
	}
	pendingSpans := leaveSpans(w, pendingLeave, holidays)
	got := capacityWeeks(w, day("2026-11-30"), day("2026-12-27"), spans, pendingSpans, holidays)
	want := []struct{ start, hours, leave, holiday, pending string }{
		{"2026-11-30", "16", "16", "8", "0"},
		{"2026-12-07", "36", "4", "0", "4"},
		{"2026-12-14", "40", "0", "0", "8"},
		{"2026-12-21", "40", "0", "0", "0"},
	}
	if len(got) != len(want) {
		t.Fatalf("weeks %+v", got)
	}
	for i, wk := range want {
		g := got[i]
		if g.WeekStart != wk.start || !g.Hours.Equal(dec(wk.hours)) || !g.LeaveHours.Equal(dec(wk.leave)) ||
			!g.HolidayHours.Equal(dec(wk.holiday)) || !g.PendingLeaveHours.Equal(dec(wk.pending)) {
			t.Errorf("week %d = %s %s/%s/%s pending %s, want %+v", i, g.WeekStart, g.Hours, g.LeaveHours, g.HolidayHours, g.PendingLeaveHours, wk)
		}
	}
}

// A county holiday applies to people whose region (or its parent) carries that county's name or
// code, in any case; national holidays apply to everyone.
func TestHolidaysFor(t *testing.T) {
	national := map[time.Time]bool{day("2026-12-12"): true}
	byCounty := map[string][]time.Time{"mombasa": {day("2026-11-25")}, "047": {day("2026-11-26")}}
	if got := holidaysFor(national, byCounty, nil); len(got) != 1 || !got[day("2026-12-12")] {
		t.Fatalf("no county = %v, want national only", got)
	}
	got := holidaysFor(national, byCounty, []string{"mombasa", "coast"})
	if len(got) != 2 || !got[day("2026-11-25")] || got[day("2026-11-26")] {
		t.Fatalf("mombasa = %v", got)
	}
	if got := holidaysFor(national, byCounty, []string{countyKey(" 047 ")}); !got[day("2026-11-26")] {
		t.Fatalf("county by code = %v", got)
	}
	if len(national) != 1 {
		t.Fatal("holidaysFor must not change the national map")
	}
}

func TestMondayOf(t *testing.T) {
	for in, want := range map[string]string{"2026-11-17": "2026-11-16", "2026-11-16": "2026-11-16", "2026-11-22": "2026-11-16"} {
		if got := mondayOf(day(in)).Format(time.DateOnly); got != want {
			t.Errorf("mondayOf(%s) = %s, want %s", in, got, want)
		}
	}
}
