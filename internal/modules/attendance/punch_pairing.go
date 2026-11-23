package attendance

import (
	"sort"
	"time"

	"github.com/google/uuid"
)

// punchLite is the part of a punch the pairing needs.
type punchLite struct {
	ID     uuid.UUID
	At     time.Time
	Status int
}

// ZKTeco punch states. 0 is also what a device without state keys sends for every punch, so it
// counts as either an arrival or a departure; 255 means "auto" and is treated the same way.
const (
	stateOut      = 1
	stateBreakOut = 2
	stateBreakIn  = 3
	stateOTIn     = 4
	stateOTOut    = 5
)

// canStartDay reports whether a punch state can be the day's first arrival.
func canStartDay(st int) bool {
	return st != stateOut && st != stateBreakOut && st != stateBreakIn && st != stateOTOut
}

// canEndDay reports whether a punch state can be the day's last departure.
func canEndDay(st int) bool {
	return st != stateBreakOut && st != stateBreakIn && st != stateOTIn
}

// pairPunches returns the day's check-in (first arrival) and check-out (last departure) from
// its punches. Punches within windowMin minutes of the previous kept punch are repeats (a
// second finger, a double tap) and are ignored. Break punches never open or close the day. A
// departure must come at least windowMin minutes after the check-in, so a single punch leaves
// the record open.
func pairPunches(ps []punchLite, windowMin int) (in, out *time.Time) {
	if len(ps) == 0 {
		return nil, nil
	}
	sorted := append([]punchLite(nil), ps...)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].At.Before(sorted[j].At) })
	window := time.Duration(windowMin) * time.Minute
	kept := sorted[:0:0]
	for _, p := range sorted {
		if n := len(kept); n > 0 && p.At.Sub(kept[n-1].At) < window {
			continue
		}
		kept = append(kept, p)
	}
	for i := range kept {
		if canStartDay(kept[i].Status) {
			t := kept[i].At
			in = &t
			break
		}
	}
	if in == nil {
		t := kept[0].At
		in = &t
	}
	for i := len(kept) - 1; i >= 0; i-- {
		p := kept[i]
		if !canEndDay(p.Status) {
			continue
		}
		if p.At.Sub(*in) < window || !p.At.After(*in) {
			break
		}
		t := p.At
		out = &t
		break
	}
	return in, out
}
