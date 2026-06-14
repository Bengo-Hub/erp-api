package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/timesheet"
	"github.com/Bengo-Hub/erp-api/internal/ent/timesheetentry"
)

// ListTimesheets returns timesheets filtered by tenant (+ optional employee).
func (s *Service) ListTimesheets(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.Timesheet, error) {
	q := s.orm.Timesheet.Query().Where(timesheet.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(timesheet.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(timesheet.FieldPeriodStart)).All(ctx)
}

// CreateTimesheet opens a draft timesheet for an employee/period.
func (s *Service) CreateTimesheet(ctx context.Context, tenantID, employeeID uuid.UUID, start, end time.Time, notes string) (*ent.Timesheet, error) {
	if end.Before(start) {
		return nil, fmt.Errorf("attendance: period_end before period_start")
	}
	b := s.orm.Timesheet.Create().
		SetTenantID(tenantID).SetEmployeeID(employeeID).
		SetPeriodStart(start).SetPeriodEnd(end).SetStatus(timesheet.StatusDraft)
	if notes != "" {
		b = b.SetNotes(notes)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create timesheet: %w", err)
	}
	return row, nil
}

// EntryInput upserts a daily timesheet entry.
type EntryInput struct {
	TimesheetID   uuid.UUID
	ProjectID     *uuid.UUID
	Date          time.Time
	Task          string
	RegularHours  string
	OvertimeHours string
	BreakHours    string
}

// UpsertEntry creates/updates a daily entry and rolls up the timesheet totals.
func (s *Service) UpsertEntry(ctx context.Context, tenantID uuid.UUID, in EntryInput) (*ent.TimesheetEntry, error) {
	reg, err := parseDecimalDefault(in.RegularHours)
	if err != nil {
		return nil, fmt.Errorf("attendance: regular_hours: %w", err)
	}
	ot, err := parseDecimalDefault(in.OvertimeHours)
	if err != nil {
		return nil, fmt.Errorf("attendance: overtime_hours: %w", err)
	}
	brk, err := parseDecimalDefault(in.BreakHours)
	if err != nil {
		return nil, fmt.Errorf("attendance: break_hours: %w", err)
	}

	existing, err := s.orm.TimesheetEntry.Query().Where(
		timesheetentry.TenantID(tenantID),
		timesheetentry.TimesheetID(in.TimesheetID),
		timesheetentry.Date(in.Date),
	).First(ctx)
	var row *ent.TimesheetEntry
	if ent.IsNotFound(err) {
		b := s.orm.TimesheetEntry.Create().
			SetTenantID(tenantID).SetTimesheetID(in.TimesheetID).SetDate(in.Date).
			SetTaskDescription(in.Task).SetRegularHours(reg).SetOvertimeHours(ot).SetBreakHours(brk)
		if in.ProjectID != nil {
			b = b.SetProjectID(*in.ProjectID)
		}
		row, err = b.Save(ctx)
	} else if err == nil {
		u := existing.Update().SetTaskDescription(in.Task).
			SetRegularHours(reg).SetOvertimeHours(ot).SetBreakHours(brk)
		if in.ProjectID != nil {
			u = u.SetProjectID(*in.ProjectID)
		}
		row, err = u.Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: upsert entry: %w", err)
	}
	if rerr := s.recalcTotals(ctx, tenantID, in.TimesheetID); rerr != nil {
		return nil, rerr
	}
	return row, nil
}

// recalcTotals recomputes a timesheet's total/overtime hours from its entries.
func (s *Service) recalcTotals(ctx context.Context, tenantID, timesheetID uuid.UUID) error {
	entries, err := s.orm.TimesheetEntry.Query().Where(
		timesheetentry.TenantID(tenantID),
		timesheetentry.TimesheetID(timesheetID),
	).All(ctx)
	if err != nil {
		return fmt.Errorf("attendance: load entries: %w", err)
	}
	total := decimal.Zero
	ot := decimal.Zero
	for _, e := range entries {
		total = total.Add(e.RegularHours)
		ot = ot.Add(e.OvertimeHours)
	}
	if _, uerr := s.orm.Timesheet.Update().
		Where(timesheet.TenantID(tenantID), timesheet.ID(timesheetID)).
		SetTotalHours(total).SetTotalOvertimeHours(ot).Save(ctx); uerr != nil {
		return fmt.Errorf("attendance: update totals: %w", uerr)
	}
	return nil
}

// SubmitTimesheet transitions draft -> submitted. Rejects invalid transitions.
func (s *Service) SubmitTimesheet(ctx context.Context, tenantID, id uuid.UUID) (*ent.Timesheet, error) {
	ts, err := s.getTimesheet(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if ts.Status != timesheet.StatusDraft && ts.Status != timesheet.StatusRejected {
		return nil, fmt.Errorf("attendance: cannot submit a %s timesheet", ts.Status)
	}
	return ts.Update().SetStatus(timesheet.StatusSubmitted).SetSubmissionDate(time.Now().UTC()).Save(ctx)
}

// ApproveTimesheet transitions submitted -> approved. Rejects invalid transitions.
func (s *Service) ApproveTimesheet(ctx context.Context, tenantID, id uuid.UUID, approverID *uuid.UUID) (*ent.Timesheet, error) {
	ts, err := s.getTimesheet(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if ts.Status != timesheet.StatusSubmitted {
		return nil, fmt.Errorf("attendance: cannot approve a %s timesheet", ts.Status)
	}
	u := ts.Update().SetStatus(timesheet.StatusApproved).SetApprovalDate(time.Now().UTC())
	if approverID != nil {
		u = u.SetApproverID(*approverID)
	}
	return u.Save(ctx)
}

// RejectTimesheet transitions submitted -> rejected with a reason. Rejects invalid transitions.
func (s *Service) RejectTimesheet(ctx context.Context, tenantID, id uuid.UUID, reason string) (*ent.Timesheet, error) {
	ts, err := s.getTimesheet(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if ts.Status != timesheet.StatusSubmitted {
		return nil, fmt.Errorf("attendance: cannot reject a %s timesheet", ts.Status)
	}
	return ts.Update().SetStatus(timesheet.StatusRejected).SetRejectionReason(reason).Save(ctx)
}

func (s *Service) getTimesheet(ctx context.Context, tenantID, id uuid.UUID) (*ent.Timesheet, error) {
	ts, err := s.orm.Timesheet.Query().Where(timesheet.TenantID(tenantID), timesheet.ID(id)).Only(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: load timesheet: %w", err)
	}
	return ts, nil
}
