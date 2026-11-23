package attendance

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshiftschedule"
)

// Record list bounds: without dates a list covers the last DefaultRecordRangeDays days, and no
// list spans more than MaxRecordRangeDays.
const (
	DefaultRecordRangeDays = 31
	MaxRecordRangeDays     = 366
)

// ErrEmployeeNotFound is returned when the employee is not in the tenant.
var ErrEmployeeNotFound = errors.New("attendance: employee not found")

// RecordFilter narrows an attendance record list.
type RecordFilter struct {
	EmployeeID *uuid.UUID
	OutletID   *uuid.UUID
	Status     string
	From, To   *time.Time
}

// boundRange fills in and clamps a date range: To defaults to today, From to To minus the
// default window, and a longer span is cut to the maximum counted back from To.
func boundRange(from, to *time.Time, now time.Time) (time.Time, time.Time) {
	hi := dateOnly(now)
	if to != nil {
		hi = dateOnly(*to)
	}
	lo := hi.AddDate(0, 0, -(DefaultRecordRangeDays - 1))
	if from != nil {
		lo = dateOnly(*from)
	}
	if hi.Sub(lo) > time.Duration(MaxRecordRangeDays)*24*time.Hour {
		lo = hi.AddDate(0, 0, -MaxRecordRangeDays)
	}
	return lo, hi
}

// ListRecords returns one page of tenant attendance records, newest first, paged in SQL over a
// bounded date range, with the total for the range.
func (s *Service) ListRecords(ctx context.Context, tenantID uuid.UUID, f RecordFilter, limit, offset int) ([]*ent.AttendanceRecord, int, error) {
	lo, hi := boundRange(f.From, f.To, time.Now())
	q := s.orm.AttendanceRecord.Query().Where(
		attendancerecord.TenantID(tenantID),
		attendancerecord.DateGTE(lo), attendancerecord.DateLT(hi.AddDate(0, 0, 1)),
	)
	if f.EmployeeID != nil {
		q = q.Where(attendancerecord.EmployeeID(*f.EmployeeID))
	}
	if f.OutletID != nil {
		q = q.Where(attendancerecord.OutletID(*f.OutletID))
	}
	if f.Status != "" {
		q = q.Where(attendancerecord.StatusEQ(attendancerecord.Status(f.Status)))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("attendance: count records: %w", err)
	}
	rows, err := q.Order(ent.Desc(attendancerecord.FieldDate), ent.Desc(attendancerecord.FieldCheckIn)).
		Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("attendance: list records: %w", err)
	}
	return rows, total, nil
}

// CheckInInput is the payload for an employee check-in.
type CheckInInput struct {
	EmployeeID  uuid.UUID
	WorkShiftID *uuid.UUID // forces a shift; nil resolves the planned one
	Date        time.Time  // zero derives the work day from the check-in time
	CheckIn     time.Time
	OutletID    *uuid.UUID // nil uses the employee's outlet
	BiometricID string
	GPSLat      string
	GPSLng      string
	Source      string         // web | mobile | manual | device; empty means web
	Metadata    map[string]any // merged into the record metadata (geo, flagged, photo_url)
}

// dayContext is the resolved policy for one employee day.
type dayContext struct {
	WorkDate time.Time
	Shift    DayShift
	Loc      *time.Location
	Rule     *ent.AttendanceRule
	Settings Settings
	OutletID *uuid.UUID
}

// resolveDay works out the work day, planned shift, zone and overtime rule for a check-in or
// check-out at t. A zero date means "derive it": a punch shortly after a night shift's end
// belongs to the day the shift started.
func (s *Service) resolveDay(ctx context.Context, tenantID uuid.UUID, emp *ent.Employee, outlet *uuid.UUID, date, t time.Time, forced *uuid.UUID, explicit bool) (*dayContext, error) {
	st, err := s.GetSettings(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	zones, err := s.loadZones(ctx, tenantID)
	if err != nil {
		return nil, fmt.Errorf("attendance: zones: %w", err)
	}
	if outlet == nil {
		outlet = emp.OutletID
	}
	keys := []empDay{{emp.ID, dateOnly(date)}}
	derive := date.IsZero()
	if derive {
		d := localDate(t, zones.For(outlet))
		keys = []empDay{{emp.ID, d.AddDate(0, 0, -1)}, {emp.ID, d}}
	}
	shifts, err := s.resolveShifts(ctx, tenantID, keys, st)
	if err != nil {
		return nil, err
	}
	workDate := keys[len(keys)-1].Day
	if derive {
		workDate = attributeWorkDate(t, workDate, shifts[keys[0]], st, zones.For(outlet, shifts[keys[0]].OutletID))
	}
	ds := shifts[empDay{emp.ID, workDate}]
	if forced != nil && (explicit || ds.Source == ShiftFromNone) && (ds.ShiftID == nil || *ds.ShiftID != *forced) {
		if fs, ferr := s.shiftDay(ctx, tenantID, *forced, workDate, st); ferr == nil && fs.ShiftID != nil {
			ds = fs
			ds.Source = "forced"
		}
	}
	rules, err := s.loadRuleSet(ctx, tenantID, []uuid.UUID{emp.ID})
	if err != nil {
		return nil, err
	}
	return &dayContext{
		WorkDate: workDate, Shift: ds, Loc: zones.For(outlet, ds.OutletID),
		Rule: rules.pick(emp.ID, outlet), Settings: st, OutletID: outlet,
	}, nil
}

// attributeWorkDate returns the previous day when t falls before the end of yesterday's night
// shift plus the overnight cutoff, else localDay.
func attributeWorkDate(t, localDay time.Time, prev DayShift, st Settings, loc *time.Location) time.Time {
	if prev.Off || !prev.Overnight() {
		return localDay
	}
	prevDay := localDay.AddDate(0, 0, -1)
	if _, end, ok := shiftWindow(prevDay, prev.Start, prev.End, loc); ok &&
		t.Before(end.Add(time.Duration(st.OvernightCutoffHours)*time.Hour)) {
		return prevDay
	}
	return localDay
}

// shiftDay loads one shift with its schedule and returns its plan for date.
func (s *Service) shiftDay(ctx context.Context, tenantID, shiftID uuid.UUID, date time.Time, st Settings) (DayShift, error) {
	sh, err := s.orm.WorkShift.Query().Where(workshift.TenantID(tenantID), workshift.ID(shiftID)).Only(ctx)
	if err != nil {
		return DayShift{}, err
	}
	scheds, err := s.orm.WorkShiftSchedule.Query().Where(
		workshiftschedule.TenantID(tenantID), workshiftschedule.WorkShiftID(shiftID)).All(ctx)
	if err != nil {
		return DayShift{}, err
	}
	cat := newShiftCatalog([]*ent.WorkShift{sh})
	cat.addSchedules(scheds)
	return cat.day(shiftID, date, st), nil
}

func (s *Service) loadEmployee(ctx context.Context, tenantID, id uuid.UUID) (*ent.Employee, error) {
	emp, err := s.orm.Employee.Query().Where(employee.TenantID(tenantID), employee.ID(id)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrEmployeeNotFound
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: load employee: %w", err)
	}
	return emp, nil
}

// CheckIn records a check-in for the employee's work day, creating the row if needed. It sets
// the outlet, resolves the planned shift (override, roster, standard shift, tenant default)
// and flags lateness against the shift start in the outlet's zone.
func (s *Service) CheckIn(ctx context.Context, tenantID uuid.UUID, in CheckInInput) (*ent.AttendanceRecord, error) {
	emp, err := s.loadEmployee(ctx, tenantID, in.EmployeeID)
	if err != nil {
		return nil, err
	}
	dc, err := s.resolveDay(ctx, tenantID, emp, in.OutletID, in.Date, in.CheckIn, in.WorkShiftID, true)
	if err != nil {
		return nil, err
	}
	existing, err := s.orm.AttendanceRecord.Query().Where(
		attendancerecord.TenantID(tenantID),
		attendancerecord.EmployeeID(in.EmployeeID),
		attendancerecord.Date(dc.WorkDate),
	).Only(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return nil, fmt.Errorf("attendance: record lookup: %w", err)
	}
	checkIn := in.CheckIn
	var checkOut *time.Time
	meta := map[string]any{}
	if existing != nil {
		checkOut = existing.CheckOut
		for k, v := range existing.Metadata {
			meta[k] = v
		}
	}
	res := evaluate(evalInput{CheckIn: &checkIn, CheckOut: checkOut, WorkDate: dc.WorkDate,
		Shift: dc.Shift, Loc: dc.Loc, Rule: dc.Rule, Settings: dc.Settings})
	source := in.Source
	if source == "" {
		source = "web"
	}
	for k, v := range in.Metadata {
		meta[k] = v
	}
	meta["source"] = source
	stampResult(meta, res, dc.Shift)

	var row *ent.AttendanceRecord
	if existing == nil {
		b := s.orm.AttendanceRecord.Create().
			SetTenantID(tenantID).SetEmployeeID(in.EmployeeID).SetDate(dc.WorkDate).
			SetCheckIn(checkIn).SetStatus(attendancerecord.Status(res.Status)).
			SetNillableOutletID(dc.OutletID).SetNillableWorkShiftID(dc.Shift.ShiftID).SetMetadata(meta)
		if in.BiometricID != "" {
			b = b.SetBiometricID(in.BiometricID)
		}
		if lat, perr := parseDecimalDefault(in.GPSLat); perr == nil && in.GPSLat != "" {
			b = b.SetGpsLatitude(lat)
		}
		if lng, perr := parseDecimalDefault(in.GPSLng); perr == nil && in.GPSLng != "" {
			b = b.SetGpsLongitude(lng)
		}
		row, err = b.Save(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: create record: %w", err)
		}
	} else {
		upd := existing.Update().SetCheckIn(checkIn).SetStatus(attendancerecord.Status(res.Status)).
			SetNillableOutletID(dc.OutletID).SetNillableWorkShiftID(dc.Shift.ShiftID).SetMetadata(meta)
		if checkOut != nil {
			upd = upd.SetTotalSecondsWorked(res.Seconds).SetRegularHours(res.Regular).SetOvertimeHours(res.Overtime)
		}
		row, err = upd.Save(ctx)
		if err != nil {
			return nil, fmt.Errorf("attendance: update check-in: %w", err)
		}
	}
	s.publishRecord(ctx, row)
	return row, nil
}

// CheckOut records a check-out and computes regular/overtime hours, early leave and half-day.
func (s *Service) CheckOut(ctx context.Context, tenantID, recordID uuid.UUID, checkOut time.Time) (*ent.AttendanceRecord, error) {
	return s.CheckOutWith(ctx, tenantID, recordID, checkOut, nil)
}

// CheckOutWith is CheckOut with extra metadata merged into the record (geo, photo, source).
func (s *Service) CheckOutWith(ctx context.Context, tenantID, recordID uuid.UUID, checkOut time.Time, extra map[string]any) (*ent.AttendanceRecord, error) {
	rec, err := s.orm.AttendanceRecord.Query().
		Where(attendancerecord.TenantID(tenantID), attendancerecord.ID(recordID)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: load record: %w", err)
	}
	if rec.CheckIn == nil {
		return nil, fmt.Errorf("attendance: cannot check out without a check-in")
	}
	if checkOut.Before(*rec.CheckIn) {
		return nil, fmt.Errorf("attendance: check_out before check_in")
	}
	emp, err := s.loadEmployee(ctx, tenantID, rec.EmployeeID)
	if err != nil {
		return nil, err
	}
	dc, err := s.resolveDay(ctx, tenantID, emp, rec.OutletID, rec.Date, checkOut, rec.WorkShiftID, false)
	if err != nil {
		return nil, err
	}
	res := evaluate(evalInput{CheckIn: rec.CheckIn, CheckOut: &checkOut, WorkDate: dateOnly(rec.Date),
		Shift: dc.Shift, Loc: dc.Loc, Rule: dc.Rule, Settings: dc.Settings})
	meta := map[string]any{}
	for k, v := range rec.Metadata {
		meta[k] = v
	}
	for k, v := range extra {
		meta[k] = v
	}
	stampResult(meta, res, dc.Shift)
	row, err := rec.Update().
		SetCheckOut(checkOut).
		SetTotalSecondsWorked(res.Seconds).
		SetRegularHours(res.Regular).
		SetOvertimeHours(res.Overtime).
		SetStatus(attendancerecord.Status(res.Status)).
		SetMetadata(meta).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: check-out update: %w", err)
	}
	s.publishRecord(ctx, row)
	return row, nil
}

// stampResult writes the derived figures into record metadata.
func stampResult(meta map[string]any, res evalResult, ds DayShift) {
	meta["late_minutes"] = res.LateMinutes
	meta["early_leave_minutes"] = res.EarlyLeaveMinutes
	meta["early_leave"] = res.EarlyLeaveMinutes > 0
	meta["shift_source"] = ds.Source
	if ds.Start != "" {
		meta["shift_start"] = ds.Start
		meta["shift_end"] = ds.End
	}
	if ds.Off {
		meta["planned_off"] = true
	}
}

// publishRecord emits erp.attendance.record.updated for a saved record.
func (s *Service) publishRecord(ctx context.Context, r *ent.AttendanceRecord) {
	payload := map[string]any{
		"record_id":   r.ID.String(),
		"employee_id": r.EmployeeID.String(),
		"date":        dateOnly(r.Date).Format("2006-01-02"),
		"status":      string(r.Status),
	}
	if r.CheckIn != nil {
		payload["check_in"] = r.CheckIn.UTC().Format(time.RFC3339)
	}
	if r.CheckOut != nil {
		payload["check_out"] = r.CheckOut.UTC().Format(time.RFC3339)
	}
	s.publish(ctx, r.TenantID, r.ID, "attendance.record.updated", payload)
}
