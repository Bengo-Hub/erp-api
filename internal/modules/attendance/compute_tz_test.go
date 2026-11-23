package attendance

import (
	"testing"
	"time"
)

func nairobi(t *testing.T) *time.Location {
	t.Helper()
	loc, err := time.LoadLocation("Africa/Nairobi")
	if err != nil {
		t.Fatal(err)
	}
	return loc
}

// A check-in stored in UTC must be compared with the shift start in the business zone: 05:20 UTC
// is 08:20 in Nairobi, 20 minutes after an 08:00 start (the old code compared 05:20 to 08:00).
func TestLateMinutesUsesBusinessZone(t *testing.T) {
	loc := nairobi(t)
	day := time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)
	checkIn := time.Date(2026, 11, 23, 5, 20, 0, 0, time.UTC)
	if got := lateMinutesAt(checkIn, day, "08:00", 15, loc); got != 20 {
		t.Fatalf("late minutes = %d, want 20", got)
	}
	if !isLate(checkIn, loc, "08:00", 15) {
		t.Fatal("isLate = false, want true")
	}
	onTime := time.Date(2026, 11, 23, 5, 10, 0, 0, time.UTC) // 08:10 local, inside the grace
	if got := lateMinutesAt(onTime, day, "08:00", 15, loc); got != 0 {
		t.Fatalf("within grace: late minutes = %d, want 0", got)
	}
	if isLate(onTime, time.UTC, "08:00", 15) {
		t.Fatal("05:10 UTC against 08:00 UTC must not be late")
	}
}

// A night shift starts on the work day and ends the next morning.
func TestNightShiftWindowAndEarlyLeave(t *testing.T) {
	loc := nairobi(t)
	day := time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)
	from, to, ok := shiftWindow(day, "22:00", "06:00", loc)
	if !ok || to.Sub(from) != 8*time.Hour {
		t.Fatalf("window %v to %v ok=%v, want 8h", from, to, ok)
	}
	// Arriving 00:30 the next morning is 150 minutes late for the 22:00 start.
	late := time.Date(2026, 11, 24, 0, 30, 0, 0, loc)
	if got := lateMinutesAt(late, day, "22:00", 10, loc); got != 150 {
		t.Fatalf("night late = %d, want 150", got)
	}
	// Leaving 05:00 is 60 minutes early; 05:55 is inside a 10 minute grace.
	if got := earlyLeaveMinutes(time.Date(2026, 11, 24, 5, 0, 0, 0, loc), day, "22:00", "06:00", 10, loc); got != 60 {
		t.Fatalf("early leave = %d, want 60", got)
	}
	if got := earlyLeaveMinutes(time.Date(2026, 11, 24, 5, 55, 0, 0, loc), day, "22:00", "06:00", 10, loc); got != 0 {
		t.Fatalf("early leave within grace = %d, want 0", got)
	}
}

// A punch shortly after a night shift's end belongs to the day the shift started.
func TestAttributeWorkDate(t *testing.T) {
	loc := nairobi(t)
	st := DefaultSettings()
	today := time.Date(2026, 11, 24, 0, 0, 0, 0, time.UTC)
	night := DayShift{Start: "22:00", End: "06:00", Source: ShiftFromEmployee}
	out := time.Date(2026, 11, 24, 6, 5, 0, 0, loc)
	if got := attributeWorkDate(out, today, night, st, loc); !got.Equal(today.AddDate(0, 0, -1)) {
		t.Fatalf("06:05 after a night shift went to %v, want previous day", got)
	}
	later := time.Date(2026, 11, 24, 11, 0, 0, 0, loc) // past end + 4h cutoff
	if got := attributeWorkDate(later, today, night, st, loc); !got.Equal(today) {
		t.Fatalf("11:00 went to %v, want today", got)
	}
	day := DayShift{Start: "08:00", End: "17:00"}
	if got := attributeWorkDate(out, today, day, st, loc); !got.Equal(today) {
		t.Fatalf("day shift yesterday must not pull the punch back, got %v", got)
	}
}

func TestEvaluateUsesSettingsFallbacks(t *testing.T) {
	loc := nairobi(t)
	st := DefaultSettings()
	day := time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)
	in := time.Date(2026, 11, 23, 8, 30, 0, 0, loc)
	out := time.Date(2026, 11, 23, 19, 30, 0, 0, loc) // 11h worked
	res := evaluate(evalInput{CheckIn: &in, CheckOut: &out, WorkDate: day,
		Shift: DayShift{Start: "08:00", End: "17:00", Grace: 15}, Loc: loc, Settings: st})
	if res.Status != "late" || res.LateMinutes != 30 {
		t.Fatalf("status %s late %d, want late 30", res.Status, res.LateMinutes)
	}
	if res.Overtime.String() != "3" || res.Regular.String() != "8" {
		t.Fatalf("regular %s overtime %s, want 8 and 3", res.Regular, res.Overtime)
	}
	st.OTThresholdHours = dec("10")
	res = evaluate(evalInput{CheckIn: &in, CheckOut: &out, WorkDate: day,
		Shift: DayShift{Start: "08:00", End: "17:00", Grace: 15}, Loc: loc, Settings: st})
	if res.Overtime.String() != "1" {
		t.Fatalf("overtime with a 10h tenant threshold = %s, want 1", res.Overtime)
	}
	early := time.Date(2026, 11, 23, 12, 0, 0, 0, loc) // 3.5h: half-day and early leave
	res = evaluate(evalInput{CheckIn: &in, CheckOut: &early, WorkDate: day,
		Shift: DayShift{Start: "08:00", End: "17:00", Grace: 15}, Loc: loc, Settings: DefaultSettings()})
	if res.Status != "half-day" || res.EarlyLeaveMinutes != 300 {
		t.Fatalf("status %s early %d, want half-day 300", res.Status, res.EarlyLeaveMinutes)
	}
}

func TestSettingsValidate(t *testing.T) {
	st := DefaultSettings()
	if err := st.Validate(); err != nil {
		t.Fatalf("defaults invalid: %v", err)
	}
	st.GeoMode = "maybe"
	if st.Validate() == nil {
		t.Fatal("bad geo_mode accepted")
	}
	st = DefaultSettings()
	st.DefaultWorkingDays = []string{"Funday"}
	if st.Validate() == nil {
		t.Fatal("bad weekday accepted")
	}
}
