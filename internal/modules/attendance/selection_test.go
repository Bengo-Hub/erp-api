package attendance

import (
	"testing"
	"time"

	"github.com/Bengo-Hub/httpware/geo"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/staffshiftoverride"
)

func at(h, m int) time.Time { return time.Date(2026, 11, 23, h, m, 0, 0, time.UTC) }

func TestPairPunches(t *testing.T) {
	id := uuid.New
	// Double tap at 07:58 and 07:59 (inside a 2 minute window), a break, then check-out.
	in, out := pairPunches([]punchLite{
		{id(), at(17, 2), 0}, {id(), at(7, 58), 0}, {id(), at(7, 59), 0},
		{id(), at(12, 0), stateBreakOut}, {id(), at(13, 0), stateBreakIn},
	}, 2)
	if in == nil || !in.Equal(at(7, 58)) || out == nil || !out.Equal(at(17, 2)) {
		t.Fatalf("in %v out %v", in, out)
	}
	// A single punch leaves the day open.
	in, out = pairPunches([]punchLite{{id(), at(8, 0), 0}}, 2)
	if in == nil || out != nil {
		t.Fatalf("single punch in %v out %v", in, out)
	}
	// Explicit states win: the 08:00 check-out code cannot open the day.
	in, out = pairPunches([]punchLite{{id(), at(8, 0), stateOut}, {id(), at(8, 30), 0}, {id(), at(16, 0), stateOut}}, 2)
	if !in.Equal(at(8, 30)) || !out.Equal(at(16, 0)) {
		t.Fatalf("state codes: in %v out %v", in, out)
	}
	// Overtime out ends the day after a normal check-out.
	_, out = pairPunches([]punchLite{{id(), at(8, 0), 0}, {id(), at(17, 0), stateOut}, {id(), at(17, 5), stateOTIn}, {id(), at(20, 0), stateOTOut}}, 2)
	if !out.Equal(at(20, 0)) {
		t.Fatalf("overtime out %v", out)
	}
}

func TestCycleDay(t *testing.T) {
	start := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	cases := map[int]int{0: 1, 13: 14, 14: 1, 15: 2, -1: 14}
	for offset, want := range cases {
		if got := cycleDay(start.AddDate(0, 0, offset), start, 14); got != want {
			t.Fatalf("offset %d: cycle day %d, want %d", offset, got, want)
		}
	}
}

func TestResolveOnePrecedence(t *testing.T) {
	st := DefaultSettings()
	emp := uuid.New()
	monday := time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)
	std := &ent.WorkShift{ID: uuid.New(), Name: "Office", GraceMinutes: 10}
	s8, e5 := "08:00", "17:00"
	std.StartTime, std.EndTime = &s8, &e5
	def := &ent.WorkShift{ID: uuid.New(), Name: "Regular", IsDefault: true, GraceMinutes: 15}
	cat := newShiftCatalog([]*ent.WorkShift{std, def})
	empShift := map[uuid.UUID]uuid.UUID{emp: std.ID}
	k := empDay{emp, monday}
	noSlot := func(*ent.ShiftAssignment) (*ent.ShiftRosterSlot, bool) { return nil, false }

	if ds := resolveOne(k, nil, nil, noSlot, empShift, cat, st); ds.Source != ShiftFromEmployee || ds.Start != "08:00" || ds.Grace != 10 {
		t.Fatalf("standard shift: %+v", ds)
	}
	if ds := resolveOne(k, nil, nil, noSlot, map[uuid.UUID]uuid.UUID{}, cat, st); ds.Source != ShiftFromDefault {
		t.Fatalf("default shift: %+v", ds)
	}
	// Saturday is not a default working day for a shift without schedule rows.
	if ds := resolveOne(empDay{emp, monday.AddDate(0, 0, 5)}, nil, nil, noSlot, empShift, cat, st); !ds.Off {
		t.Fatalf("saturday must be off: %+v", ds)
	}
	ns, ne := "22:00", "06:00"
	slot := &ent.ShiftRosterSlot{StartTime: &ns, EndTime: &ne}
	assign := []*ent.ShiftAssignment{{StartDate: monday.AddDate(0, 0, -7), RosterID: uuid.New()}}
	withSlot := func(*ent.ShiftAssignment) (*ent.ShiftRosterSlot, bool) { return slot, true }
	ds := resolveOne(k, nil, assign, withSlot, empShift, cat, st)
	if ds.Source != ShiftFromRoster || !ds.Overnight() || ds.Grace != 10 {
		t.Fatalf("roster slot: %+v", ds)
	}
	off := &ent.StaffShiftOverride{OverrideType: staffshiftoverride.OverrideTypeOffDuty}
	if ds := resolveOne(k, off, assign, withSlot, empShift, cat, st); ds.Source != ShiftFromOverride || !ds.Off {
		t.Fatalf("override wins: %+v", ds)
	}
}

func TestSelectExpectedForAutoAbsent(t *testing.T) {
	day := time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)
	working, off, unknown, county := uuid.New(), uuid.New(), uuid.New(), uuid.New()
	keys := []empDay{{working, day}, {off, day}, {unknown, day}, {county, day}}
	shifts := map[empDay]DayShift{
		{working, day}: {Source: ShiftFromEmployee, Start: "08:00"},
		{off, day}:     {Source: ShiftFromRoster, Off: true},
		{unknown, day}: {Source: ShiftFromNone},
		{county, day}:  {Source: ShiftFromDefault, Start: "08:00"},
	}
	got := selectExpected(keys, shifts, map[string]bool{"mombasa": true}, map[uuid.UUID][]string{county: {"mombasa"}})
	if len(got) != 1 || got[0] != working {
		t.Fatalf("expected only the working employee, got %v", got)
	}
}

func TestAutoAbsentDay(t *testing.T) {
	loc := nairobi(t)
	before := time.Date(2026, 11, 23, 22, 0, 0, 0, loc)
	if d, ok := autoAbsentDay(before, loc, "23:00"); !ok || d.Day() != 22 {
		t.Fatalf("before the cut-off closes yesterday, got %v", d)
	}
	after := time.Date(2026, 11, 23, 23, 30, 0, 0, loc)
	if d, ok := autoAbsentDay(after, loc, "23:00"); !ok || d.Day() != 23 {
		t.Fatalf("after the cut-off closes today, got %v", d)
	}
}

func TestNextRotationState(t *testing.T) {
	a, b := uuid.New(), uuid.New()
	day := time.Date(2026, 11, 23, 0, 0, 0, 0, time.UTC)
	r := &ent.ShiftRotation{ShiftIds: []uuid.UUID{a, b}, RunDuration: 2, RunUnit: "Weeks", BreakDuration: 1, BreakUnit: "Day"}
	cur, last, next, ok := nextRotationState(r, day)
	if !ok || *cur != a || last != nil || !next.Equal(day.AddDate(0, 0, 15)) {
		t.Fatalf("start: cur %v last %v next %v", cur, last, next)
	}
	r.CurrentActiveShiftID = &a
	cur, last, _, _ = nextRotationState(r, day)
	if *cur != b || *last != a {
		t.Fatalf("advance: cur %v last %v", cur, last)
	}
}

func TestGeoDecision(t *testing.T) {
	site := &ent.WorkSite{ID: uuid.New(), Name: "Main gate", CenterLat: -1.2921, CenterLng: 36.8219, RadiusM: 100}
	inside := checkFence(geo.Point{Lat: -1.2925, Lng: 36.8219}, []*ent.WorkSite{site}, 0)
	if !inside.Checked || !inside.Inside {
		t.Fatalf("point 45 m from centre must be inside: %+v", inside)
	}
	far := checkFence(geo.Point{Lat: -1.3021, Lng: 36.8219}, []*ent.WorkSite{site}, toleranceFor(30, 50))
	if far.Inside || far.DistanceM < 900 || far.SiteName != "Main gate" {
		t.Fatalf("point about 1 km away: %+v", far)
	}
	if f, b := geoDecision(GeoModeFlag, false, far); !f || b {
		t.Fatal("flag mode must flag, not block")
	}
	if f, b := geoDecision(GeoModeBlock, false, far); f || !b {
		t.Fatal("block mode must block")
	}
	if f, b := geoDecision(GeoModeBlock, true, far); f || b {
		t.Fatal("field staff are never blocked or flagged")
	}
	if f, b := geoDecision(GeoModeFlag, false, inside); f || b {
		t.Fatal("inside is never flagged")
	}
	if f, b := geoDecision(GeoModeBlock, false, FenceResult{}); f || b {
		t.Fatal("no work sites configured must not block")
	}
	poly := &ent.WorkSite{ID: uuid.New(), Name: "Yard", Ring: [][]float64{{36.82, -1.29}, {36.83, -1.29}, {36.83, -1.28}, {36.82, -1.28}}}
	if c := checkFence(geo.Point{Lat: -1.285, Lng: 36.825}, []*ent.WorkSite{site, poly}, 0); !c.Inside || c.SiteName != "Yard" {
		t.Fatalf("polygon: %+v", c)
	}
	if got := toleranceFor(120, 50); got != 50 {
		t.Fatalf("tolerance capped at the tenant limit, got %v", got)
	}
}
