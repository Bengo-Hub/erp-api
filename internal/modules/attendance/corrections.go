package attendance

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerecord"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
)

// Approval modules owned by attendance.
const (
	ModuleRegularisation = "attendance_regularisation"
	ModuleOvertime       = "overtime_request"
	// fallbackApproverRole decides attendance requests for tenants without a workflow.
	fallbackApproverRole = "hrm.attendance.manage"
)

// ErrApprovalsUnavailable is returned when the approvals engine is not wired.
var ErrApprovalsUnavailable = errors.New("attendance: approvals are not configured")

// ApprovalEngine is the part of the approvals service attendance uses.
type ApprovalEngine interface {
	SubmitWithFallback(ctx context.Context, tenantID uuid.UUID, in approvals.SubmitInput, fallbackRole string) (*ent.ApprovalRequest, error)
	RegisterHook(module string, h approvals.Hook)
}

// SetApprovals wires the approvals engine and registers the apply hooks for regularisations
// and overtime requests.
func (s *Service) SetApprovals(a ApprovalEngine) {
	s.approvals = a
	if a == nil {
		return
	}
	a.RegisterHook(ModuleRegularisation, s.applyRegularisationDecision)
	a.RegisterHook(ModuleOvertime, s.applyOvertimeDecision)
}

// dayTimesUpdate is called with the record metadata (already stamped) and the evaluation
// before the record is saved, so the caller can add its own keys.
type dayTimesUpdate func(meta map[string]any, res evalResult, in, out *time.Time)

// setDayTimes writes check-in and check-out for one employee day, keeping the record's
// current value where the new one is nil, re-evaluates lateness, early leave and hours, and
// saves the record (creating it when the day had none).
func (s *Service) setDayTimes(ctx context.Context, tenantID uuid.UUID, emp *ent.Employee, date time.Time, in, out *time.Time, update dayTimesUpdate) (*ent.AttendanceRecord, error) {
	date = dateOnly(date)
	ref := date
	if in != nil {
		ref = *in
	}
	dc, err := s.resolveDay(ctx, tenantID, emp, nil, date, ref, nil, false)
	if err != nil {
		return nil, err
	}
	existing, err := s.orm.AttendanceRecord.Query().Where(attendancerecord.TenantID(tenantID),
		attendancerecord.EmployeeID(emp.ID), attendancerecord.Date(date)).Only(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return nil, fmt.Errorf("attendance: record lookup: %w", err)
	}
	meta := map[string]any{}
	if existing != nil {
		for k, v := range existing.Metadata {
			meta[k] = v
		}
		delete(meta, "auto_absent")
		if in == nil {
			in = existing.CheckIn
		}
		if out == nil {
			out = existing.CheckOut
		}
	}
	if in != nil && out != nil && out.Before(*in) {
		return nil, errors.New("check-out is before check-in")
	}
	res := evaluate(evalInput{CheckIn: in, CheckOut: out, WorkDate: date, Shift: dc.Shift, Loc: dc.Loc,
		Rule: dc.Rule, Settings: dc.Settings})
	stampResult(meta, res, dc.Shift)
	if update != nil {
		update(meta, res, in, out)
	}
	var row *ent.AttendanceRecord
	if existing == nil {
		row, err = s.orm.AttendanceRecord.Create().SetTenantID(tenantID).SetEmployeeID(emp.ID).SetDate(date).
			SetNillableCheckIn(in).SetNillableCheckOut(out).SetNillableOutletID(dc.OutletID).
			SetNillableWorkShiftID(dc.Shift.ShiftID).SetStatus(attendancerecord.Status(res.Status)).
			SetTotalSecondsWorked(res.Seconds).SetRegularHours(res.Regular).SetOvertimeHours(res.Overtime).
			SetMetadata(meta).Save(ctx)
	} else {
		u := existing.Update().SetStatus(attendancerecord.Status(res.Status)).
			SetTotalSecondsWorked(res.Seconds).SetRegularHours(res.Regular).SetOvertimeHours(res.Overtime).
			SetMetadata(meta)
		if in != nil {
			u = u.SetCheckIn(*in)
		}
		if out != nil {
			u = u.SetCheckOut(*out)
		}
		row, err = u.Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: save corrected record: %w", err)
	}
	s.publishRecord(ctx, row)
	return row, nil
}

// clockTimes parses "HH:MM" company times on a work day. A check-out not after the check-in
// belongs to the next day (night shift). Empty strings give nil.
func clockTimes(date time.Time, checkIn, checkOut string, loc *time.Location) (in, out *time.Time, err error) {
	if checkIn != "" {
		t, ok := clockOn(date, checkIn, loc)
		if !ok {
			return nil, nil, errors.New("check_in must be HH:MM")
		}
		in = &t
	}
	if checkOut != "" {
		t, ok := clockOn(date, checkOut, loc)
		if !ok {
			return nil, nil, errors.New("check_out must be HH:MM")
		}
		if in != nil && !t.After(*in) {
			t = t.Add(24 * time.Hour)
		}
		out = &t
	}
	return in, out, nil
}

// timesMap is the before or after snapshot kept in corrections[].
func timesMap(in, out *time.Time, status string) map[string]any {
	m := map[string]any{"check_in": nil, "check_out": nil, "status": status}
	if in != nil {
		m["check_in"] = in.UTC().Format(time.RFC3339)
	}
	if out != nil {
		m["check_out"] = out.UTC().Format(time.RFC3339)
	}
	return m
}

// appendCorrection adds one entry to the record metadata corrections[].
func appendCorrection(meta map[string]any, entry map[string]any) {
	var list []any
	if cur, ok := meta["corrections"].([]any); ok {
		list = cur
	}
	meta["corrections"] = append(list, entry)
}
