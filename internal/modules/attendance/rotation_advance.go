package attendance

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftrotation"
)

// addPeriod adds n units (day, week, month, year; singular or plural, any case) to t.
// Unknown units count as days.
func addPeriod(t time.Time, n int, unit string) time.Time {
	u := strings.TrimSuffix(strings.ToLower(strings.TrimSpace(unit)), "s")
	switch u {
	case "week":
		return t.AddDate(0, 0, 7*n)
	case "month":
		return t.AddDate(0, n, 0)
	case "year":
		return t.AddDate(n, 0, 0)
	default:
		return t.AddDate(0, 0, n)
	}
}

// nextRotationState is the rotation after one change at day: the next shift in shift_ids
// becomes active and the next change falls after the run plus the break. A rotation that never
// started begins with its first shift. Pure, for tests.
func nextRotationState(r *ent.ShiftRotation, day time.Time) (current, last *uuid.UUID, next time.Time, ok bool) {
	if len(r.ShiftIds) == 0 {
		return nil, nil, time.Time{}, false
	}
	idx := 0
	if r.CurrentActiveShiftID != nil {
		for i, id := range r.ShiftIds {
			if id == *r.CurrentActiveShiftID {
				idx = (i + 1) % len(r.ShiftIds)
				break
			}
		}
		last = r.CurrentActiveShiftID
	}
	cur := r.ShiftIds[idx]
	next = addPeriod(addPeriod(day, r.RunDuration, r.RunUnit), r.BreakDuration, r.BreakUnit)
	return &cur, last, next, true
}

// AdvanceRotations moves every active rotation whose next_change_date has come (or that never
// started) to its next shift, across all tenants. Returns how many rotations changed.
func (s *Service) AdvanceRotations(ctx context.Context, now time.Time) (int, error) {
	day := dateOnly(now)
	due, err := s.orm.ShiftRotation.Query().Where(
		shiftrotation.IsActive(true),
		shiftrotation.Or(shiftrotation.NextChangeDateIsNil(), shiftrotation.NextChangeDateLT(day.AddDate(0, 0, 1))),
	).All(ctx)
	if err != nil {
		return 0, fmt.Errorf("attendance: due rotations: %w", err)
	}
	n := 0
	for _, r := range due {
		cur, last, next, ok := nextRotationState(r, day)
		if !ok {
			continue
		}
		if err := s.orm.ShiftRotation.UpdateOneID(r.ID).
			SetNillableCurrentActiveShiftID(cur).SetNillableLastShiftID(last).
			SetNextChangeDate(next).Exec(ctx); err != nil {
			return n, fmt.Errorf("attendance: advance rotation %s: %w", r.ID, err)
		}
		n++
	}
	return n, nil
}
