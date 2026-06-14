package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshiftschedule"
)

// ListRecords returns attendance records filtered by tenant (+ optional employee/date range).
func (s *Service) ListRecords(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, from, to *time.Time) ([]*ent.AttendanceRecord, error) {
	q := s.orm.AttendanceRecord.Query().Where(attendancerecord.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(attendancerecord.EmployeeID(*employeeID))
	}
	if from != nil {
		q = q.Where(attendancerecord.DateGTE(*from))
	}
	if to != nil {
		q = q.Where(attendancerecord.DateLTE(*to))
	}
	return q.Order(ent.Desc(attendancerecord.FieldDate)).All(ctx)
}

// CheckInInput is the payload for an employee check-in.
type CheckInInput struct {
	EmployeeID  uuid.UUID
	WorkShiftID *uuid.UUID
	Date        time.Time
	CheckIn     time.Time
	BiometricID string
	GPSLat      string
	GPSLng      string
}

// CheckIn records a check-in for (employee, date), creating the row if needed, and flags it
// late when check-in is past the effective shift start + grace (late-detection logic).
func (s *Service) CheckIn(ctx context.Context, tenantID uuid.UUID, in CheckInInput) (*ent.AttendanceRecord, error) {
	shiftID := in.WorkShiftID
	if shiftID == nil {
		if def, err := s.orm.WorkShift.Query().
			Where(workshift.TenantID(tenantID), workshift.IsDefault(true)).First(ctx); err == nil {
			id := def.ID
			shiftID = &id
		}
	}
	status := "present"
	if s.lateForShift(ctx, tenantID, shiftID, in.Date, in.CheckIn) {
		status = "late"
	}

	existing, err := s.orm.AttendanceRecord.Query().Where(
		attendancerecord.TenantID(tenantID),
		attendancerecord.EmployeeID(in.EmployeeID),
		attendancerecord.Date(in.Date),
	).First(ctx)
	if ent.IsNotFound(err) {
		b := s.orm.AttendanceRecord.Create().
			SetTenantID(tenantID).SetEmployeeID(in.EmployeeID).
			SetDate(in.Date).SetCheckIn(in.CheckIn).SetStatus(attendancerecord.Status(status))
		if shiftID != nil {
			b = b.SetWorkShiftID(*shiftID)
		}
		if in.BiometricID != "" {
			b = b.SetBiometricID(in.BiometricID)
		}
		if lat, perr := parseDecimalDefault(in.GPSLat); perr == nil && in.GPSLat != "" {
			b = b.SetGpsLatitude(lat)
		}
		if lng, perr := parseDecimalDefault(in.GPSLng); perr == nil && in.GPSLng != "" {
			b = b.SetGpsLongitude(lng)
		}
		row, cerr := b.Save(ctx)
		if cerr != nil {
			return nil, fmt.Errorf("attendance: create record: %w", cerr)
		}
		return row, nil
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: record lookup: %w", err)
	}
	upd := existing.Update().SetCheckIn(in.CheckIn).SetStatus(attendancerecord.Status(status))
	if shiftID != nil {
		upd = upd.SetWorkShiftID(*shiftID)
	}
	row, err := upd.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: update check-in: %w", err)
	}
	return row, nil
}

// CheckOut records a check-out and computes regular/overtime hours per the active overtime
// rule, flagging half-day when worked hours fall below the rule minimum.
func (s *Service) CheckOut(ctx context.Context, tenantID, recordID uuid.UUID, checkOut time.Time) (*ent.AttendanceRecord, error) {
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
	seconds := int(checkOut.Sub(*rec.CheckIn).Seconds())

	rule, err := s.activeOvertimeRule(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	res := computeHours(computeHoursInput{
		TotalSecondsWorked: seconds,
		HasCheckOut:        true,
		Rule:               rule,
		CurrentStatus:      string(rec.Status),
	})
	row, err := rec.Update().
		SetCheckOut(checkOut).
		SetTotalSecondsWorked(seconds).
		SetRegularHours(res.RegularHours).
		SetOvertimeHours(res.OvertimeHours).
		SetStatus(attendancerecord.Status(res.Status)).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: check-out update: %w", err)
	}
	return row, nil
}

// lateForShift resolves the effective shift start (day-specific schedule, falling back to
// the shift's legacy start_time) and reports whether check-in is late.
func (s *Service) lateForShift(ctx context.Context, tenantID uuid.UUID, shiftID *uuid.UUID, date, checkIn time.Time) bool {
	if shiftID == nil {
		return false
	}
	shift, err := s.orm.WorkShift.Query().
		Where(workshift.TenantID(tenantID), workshift.ID(*shiftID)).Only(ctx)
	if err != nil {
		return false
	}
	start := ""
	if shift.StartTime != nil {
		start = *shift.StartTime
	}
	if sched, serr := s.orm.WorkShiftSchedule.Query().Where(
		workshiftschedule.TenantID(tenantID),
		workshiftschedule.WorkShiftID(*shiftID),
		workshiftschedule.DayEQ(workshiftschedule.Day(scheduleDayFor(date))),
		workshiftschedule.IsWorkingDay(true),
	).First(ctx); serr == nil {
		start = sched.StartTime
	}
	return isLate(checkIn, start, shift.GraceMinutes)
}
