package employees

import (
	"time"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// SalaryInForce picks, from one employee's salary rows, the one that applies at a moment: an
// active row starting on or before it (a row without a start applies from the beginning), the
// latest start winning and, for the same start, the newest row. Nil when none applies yet (only
// a future salary is scheduled).
func SalaryInForce(rows []*ent.SalaryDetails, at time.Time) *ent.SalaryDetails {
	var best *ent.SalaryDetails
	for _, r := range rows {
		if !r.IsActive || (r.EffectiveFrom != nil && r.EffectiveFrom.After(at)) {
			continue
		}
		if best == nil || startsLater(r, best) {
			best = r
		}
	}
	return best
}

// startsLater reports whether a applies after b (later start, else created later).
func startsLater(a, b *ent.SalaryDetails) bool {
	switch {
	case a.EffectiveFrom == nil && b.EffectiveFrom != nil:
		return false
	case a.EffectiveFrom != nil && b.EffectiveFrom == nil:
		return true
	case a.EffectiveFrom != nil && !a.EffectiveFrom.Equal(*b.EffectiveFrom):
		return a.EffectiveFrom.After(*b.EffectiveFrom)
	}
	return a.CreatedAt.After(b.CreatedAt)
}

// MonthEnd is the last moment of a payroll month (the period's first day).
func MonthEnd(period time.Time) time.Time {
	first := time.Date(period.Year(), period.Month(), 1, 0, 0, 0, 0, time.UTC)
	return first.AddDate(0, 1, 0).Add(-time.Nanosecond)
}
