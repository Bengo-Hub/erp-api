package attendance

import (
	"context"
	"time"
	_ "time/tzdata" // the runtime image (alpine) ships no zone database

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/authoutlet"
	"github.com/Bengo-Hub/erp-api/internal/ent/companysettings"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshiftschedule"
)

// defaultZone is used when neither the shift's outlet nor the company settings name a zone.
const defaultZone = "Africa/Nairobi"

// LateMinutes returns, for each record that has a check-in and a shift, how many minutes after
// the shift's start the employee checked in (0 when on time or within the grace window). The
// start is the day's working schedule, falling back to the shift's legacy start, exactly as
// check-in marks a record late. A shift start is local wall-clock time, so the stored check-in
// is read in the shift outlet's time zone (else the company's, else Africa/Nairobi), whatever
// zone the database returned it in. Shifts, schedules and zones load in four queries per batch.
func LateMinutes(ctx context.Context, orm *ent.Client, tenantID uuid.UUID, records []*ent.AttendanceRecord) (map[uuid.UUID]int, error) {
	out := make(map[uuid.UUID]int, len(records))
	shiftIDs := map[uuid.UUID]bool{}
	for _, r := range records {
		if r.WorkShiftID != nil && r.CheckIn != nil {
			shiftIDs[*r.WorkShiftID] = true
		}
	}
	if len(shiftIDs) == 0 {
		return out, nil
	}
	ids := make([]uuid.UUID, 0, len(shiftIDs))
	for id := range shiftIDs {
		ids = append(ids, id)
	}
	shifts, err := orm.WorkShift.Query().Where(workshift.TenantID(tenantID), workshift.IDIn(ids...)).All(ctx)
	if err != nil {
		return nil, err
	}
	byShift := make(map[uuid.UUID]*ent.WorkShift, len(shifts))
	for _, s := range shifts {
		byShift[s.ID] = s
	}
	scheds, err := orm.WorkShiftSchedule.Query().Where(
		workshiftschedule.TenantID(tenantID),
		workshiftschedule.WorkShiftIDIn(ids...),
		workshiftschedule.IsWorkingDay(true),
	).All(ctx)
	if err != nil {
		return nil, err
	}
	type dayKey struct {
		shift uuid.UUID
		day   string
	}
	starts := make(map[dayKey]string, len(scheds))
	for _, s := range scheds {
		k := dayKey{s.WorkShiftID, string(s.Day)}
		if _, ok := starts[k]; !ok {
			starts[k] = s.StartTime
		}
	}
	zoneOf, err := shiftZones(ctx, orm, tenantID, shifts)
	if err != nil {
		return nil, err
	}
	for _, r := range records {
		if r.WorkShiftID == nil || r.CheckIn == nil {
			continue
		}
		shift := byShift[*r.WorkShiftID]
		if shift == nil {
			continue
		}
		// The record's date is its work day (a night shift's check-in may fall after midnight),
		// and the shift start is wall-clock time in the shift's zone.
		workDate := dateOnly(r.Date)
		start := starts[dayKey{shift.ID, scheduleDayFor(workDate)}]
		if start == "" && shift.StartTime != nil {
			start = *shift.StartTime
		}
		if m := lateMinutesAt(*r.CheckIn, workDate, start, shift.GraceMinutes, zoneOf(shift)); m > 0 {
			out[r.ID] = m
		}
	}
	return out, nil
}

// shiftZones resolves each shift's time zone: its outlet's zone, else the company zone, else
// Africa/Nairobi. Unknown zone names fall through to the next choice.
func shiftZones(ctx context.Context, orm *ent.Client, tenantID uuid.UUID, shifts []*ent.WorkShift) (func(*ent.WorkShift) *time.Location, error) {
	fallback, _ := time.LoadLocation(defaultZone)
	if cs, err := orm.CompanySettings.Query().Where(companysettings.TenantID(tenantID)).First(ctx); err == nil && cs.Timezone != "" {
		if loc, lerr := time.LoadLocation(cs.Timezone); lerr == nil {
			fallback = loc
		}
	} else if err != nil && !ent.IsNotFound(err) {
		return nil, err
	}
	outletIDs := map[uuid.UUID]bool{}
	for _, s := range shifts {
		if s.OutletID != nil {
			outletIDs[*s.OutletID] = true
		}
	}
	byOutlet := map[uuid.UUID]*time.Location{}
	if len(outletIDs) > 0 {
		ids := make([]uuid.UUID, 0, len(outletIDs))
		for id := range outletIDs {
			ids = append(ids, id)
		}
		outlets, err := orm.AuthOutlet.Query().Where(authoutlet.TenantID(tenantID), authoutlet.IDIn(ids...)).All(ctx)
		if err != nil {
			return nil, err
		}
		for _, o := range outlets {
			if o.Timezone == "" {
				continue
			}
			if loc, lerr := time.LoadLocation(o.Timezone); lerr == nil {
				byOutlet[o.ID] = loc
			}
		}
	}
	return func(s *ent.WorkShift) *time.Location {
		if s.OutletID != nil {
			if loc, ok := byOutlet[*s.OutletID]; ok {
				return loc
			}
		}
		return fallback
	}, nil
}
