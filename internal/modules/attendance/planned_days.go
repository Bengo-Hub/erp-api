package attendance

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/publicholiday"
)

// Reasons a planned day is not a full working day.
const (
	DayReasonHoliday = "public_holiday"
	DayReasonOff     = "day_off"
	DayReasonHalf    = "half_day"
)

// ErrPlannedRange is returned for a reversed range or one longer than MaxCapacityDays.
var ErrPlannedRange = errors.New("the date range must be at most 366 days and end on or after its start")

// PlannedDay is one calendar day of an employee's plan: Share is 1 for a working day, 0.5 for a
// half-day override and 0 for a day off or a public holiday. Name is the holiday's name.
type PlannedDay struct {
	Date   time.Time
	Share  decimal.Decimal
	Reason string
	Name   string
}

// splitHolidays groups holiday rows into the national dates and the dates per county key.
func splitHolidays(rows []*ent.PublicHoliday) (national map[time.Time]bool, byCounty map[string][]time.Time) {
	national, byCounty = map[time.Time]bool{}, map[string][]time.Time{}
	for _, h := range rows {
		d := dateOnly(h.Date)
		if h.IsNational {
			national[d] = true
			continue
		}
		if h.County != nil {
			if k := countyKey(*h.County); k != "" {
				byCounty[k] = append(byCounty[k], d)
			}
		}
	}
	return national, byCounty
}

// PlannedDays answers every day of [from, to] for one employee, resolving shifts like attendance
// does (override, roster, own shift, company default shift). With no shift at all the tenant's
// default working days apply. Public holidays are the national ones and those of the employee's
// county; a night shift belongs to the day it starts.
func (s *Service) PlannedDays(ctx context.Context, tenantID, employeeID uuid.UUID, from, to time.Time) ([]PlannedDay, error) {
	from, to = dateOnly(from), dateOnly(to)
	if to.Before(from) || to.Sub(from) >= MaxCapacityDays*24*time.Hour {
		return nil, ErrPlannedRange
	}
	st, err := s.GetSettings(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	var keys []empDay
	for d := from; !d.After(to); d = d.AddDate(0, 0, 1) {
		keys = append(keys, empDay{employeeID, d})
	}
	shifts, err := s.resolveShifts(ctx, tenantID, keys, st)
	if err != nil {
		return nil, err
	}
	rows, err := s.orm.PublicHoliday.Query().Where(publicholiday.TenantID(tenantID),
		publicholiday.DateGTE(from), publicholiday.DateLT(to.AddDate(0, 0, 1))).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: planned holidays: %w", err)
	}
	counties, err := s.employeeCounties(ctx, tenantID, []uuid.UUID{employeeID})
	if err != nil {
		return nil, err
	}
	national, byCounty := splitHolidays(rows)
	holidays := holidaysFor(national, byCounty, counties[employeeID])
	mine := map[string]bool{}
	for _, k := range counties[employeeID] {
		mine[k] = true
	}
	names := map[time.Time]string{}
	for _, h := range rows {
		if h.IsNational || (h.County != nil && mine[countyKey(*h.County)]) {
			names[dateOnly(h.Date)] = h.Name
		}
	}

	out := make([]PlannedDay, 0, len(keys))
	for _, k := range keys {
		ds := shifts[k]
		off := ds.Off
		if ds.Source == ShiftFromNone {
			off = !containsDay(st.DefaultWorkingDays, scheduleDayFor(k.Day))
		}
		p := PlannedDay{Date: k.Day, Share: decimal.NewFromInt(1)}
		switch {
		case holidays[k.Day]:
			p.Share, p.Reason, p.Name = decimal.Zero, DayReasonHoliday, names[k.Day]
		case off:
			p.Share, p.Reason = decimal.Zero, DayReasonOff
		case ds.HalfDay:
			p.Share, p.Reason = decimal.NewFromFloat(0.5), DayReasonHalf
		}
		out = append(out, p)
	}
	return out, nil
}
