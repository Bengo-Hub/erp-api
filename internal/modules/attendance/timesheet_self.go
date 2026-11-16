package attendance

import (
	"context"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/timesheet"
	"github.com/Bengo-Hub/erp-api/internal/ent/timesheetentry"
)

// Time an employee logs for themselves, through projects-api (S2S on the employee's behalf) or
// their own sign-in. The employee's timesheet for a date is the one whose period covers it; when
// there is none, the caller's period (projects-api sends the Monday to Sunday week) is opened as a
// draft. Approval stays with ERP's own timesheet screens.

var (
	// ErrTimesheetLocked: the timesheet covering the date is submitted or approved.
	ErrTimesheetLocked = errors.New("attendance: the timesheet is submitted or approved; ask for it to be rejected before changing it")
	// ErrNothingToSubmit: no draft or rejected timesheet overlaps the range.
	ErrNothingToSubmit = errors.New("attendance: no draft or rejected timesheet in that period")
	// ErrInvalidEntry: hours or dates outside what one entry may hold.
	ErrInvalidEntry = errors.New("attendance: invalid entry")
)

// MaxEntryHours caps one entry (a date, project and task).
var MaxEntryHours = decimal.NewFromInt(24)

// EmployeeTimesheets is an employee's timesheets overlapping a range and their entries in it.
type EmployeeTimesheets struct {
	EmployeeID uuid.UUID             `json:"employee_id"`
	Timesheets []*ent.Timesheet      `json:"timesheets"`
	Entries    []*ent.TimesheetEntry `json:"entries"`
}

// overlapping returns the employee's timesheets whose period overlaps [from, to].
func (s *Service) overlapping(ctx context.Context, tenantID, employeeID uuid.UUID, from, to time.Time) ([]*ent.Timesheet, error) {
	return s.orm.Timesheet.Query().Where(
		timesheet.TenantID(tenantID), timesheet.EmployeeID(employeeID),
		timesheet.PeriodStartLTE(to), timesheet.PeriodEndGTE(from),
	).Order(ent.Asc(timesheet.FieldPeriodStart)).All(ctx)
}

// EmployeeRange returns the employee's timesheets overlapping [from, to] and their entries dated
// inside it.
func (s *Service) EmployeeRange(ctx context.Context, tenantID, employeeID uuid.UUID, from, to time.Time) (*EmployeeTimesheets, error) {
	if to.Before(from) {
		return nil, fmt.Errorf("%w: to is before from", ErrInvalidEntry)
	}
	sheets, err := s.overlapping(ctx, tenantID, employeeID, from, to)
	if err != nil {
		return nil, fmt.Errorf("attendance: employee timesheets: %w", err)
	}
	out := &EmployeeTimesheets{EmployeeID: employeeID, Timesheets: sheets, Entries: []*ent.TimesheetEntry{}}
	if len(sheets) == 0 {
		return out, nil
	}
	ids := make([]uuid.UUID, len(sheets))
	for i, ts := range sheets {
		ids[i] = ts.ID
	}
	out.Entries, err = s.orm.TimesheetEntry.Query().Where(
		timesheetentry.TenantID(tenantID), timesheetentry.TimesheetIDIn(ids...),
		timesheetentry.DateGTE(from), timesheetentry.DateLTE(to),
	).Order(ent.Asc(timesheetentry.FieldDate)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: employee entries: %w", err)
	}
	return out, nil
}

// sheetFor returns the employee's timesheet covering date, opening [periodStart, periodEnd] as a
// draft when none does.
func (s *Service) sheetFor(ctx context.Context, tenantID, employeeID uuid.UUID, date, periodStart, periodEnd time.Time) (*ent.Timesheet, error) {
	find := func() (*ent.Timesheet, error) {
		return s.orm.Timesheet.Query().Where(
			timesheet.TenantID(tenantID), timesheet.EmployeeID(employeeID),
			timesheet.PeriodStartLTE(date), timesheet.PeriodEndGTE(date),
		).Order(ent.Desc(timesheet.FieldPeriodStart)).First(ctx)
	}
	ts, err := find()
	if err == nil || !ent.IsNotFound(err) {
		return ts, err
	}
	if date.Before(periodStart) || date.After(periodEnd) {
		return nil, fmt.Errorf("%w: date outside period_start..period_end", ErrInvalidEntry)
	}
	created, cerr := s.CreateTimesheet(ctx, tenantID, employeeID, periodStart, periodEnd, "")
	if cerr == nil {
		return created, nil
	}
	// A concurrent call opened the same period first (unique per employee and period).
	if ts, err := find(); err == nil {
		return ts, nil
	}
	return nil, cerr
}

// EmployeeEntryInput logs time for an employee. Add adds Hours to the entry instead of setting it
// (a stopped timer). An empty Task keeps the entry's description.
type EmployeeEntryInput struct {
	EmployeeID  uuid.UUID
	PeriodStart time.Time
	PeriodEnd   time.Time
	Date        time.Time
	ProjectID   *uuid.UUID
	TaskID      *uuid.UUID
	Billable    *bool
	Task        string
	Hours       decimal.Decimal
	Add         bool
}

// LoggedEntry is the entry after a log, with its timesheet (totals rolled up).
type LoggedEntry struct {
	EmployeeID uuid.UUID           `json:"employee_id"`
	Timesheet  *ent.Timesheet      `json:"timesheet"`
	Entry      *ent.TimesheetEntry `json:"entry"`
}

// LogEmployeeEntry sets or adds the employee's hours for one date, project and task.
func (s *Service) LogEmployeeEntry(ctx context.Context, tenantID uuid.UUID, in EmployeeEntryInput) (*LoggedEntry, error) {
	if in.Hours.IsNegative() || in.Hours.GreaterThan(MaxEntryHours) {
		return nil, fmt.Errorf("%w: hours must be between 0 and 24", ErrInvalidEntry)
	}
	if in.PeriodEnd.Before(in.PeriodStart) {
		return nil, fmt.Errorf("%w: period_end before period_start", ErrInvalidEntry)
	}
	sheet, err := s.sheetFor(ctx, tenantID, in.EmployeeID, in.Date, in.PeriodStart, in.PeriodEnd)
	if err != nil {
		return nil, err
	}
	var row *ent.TimesheetEntry
	// The status check, the read of the current hours and the write share one timesheet lock, so a
	// submit or another add in flight cannot slip between them.
	err = s.withSheetLock(ctx, tenantID, sheet.ID, func(tx *ent.Tx, locked *ent.Timesheet) error {
		if locked.Status != timesheet.StatusDraft && locked.Status != timesheet.StatusRejected {
			return ErrTimesheetLocked
		}
		c := tx.Client()
		entry := EntryInput{
			TimesheetID: locked.ID, ProjectID: in.ProjectID, TaskID: in.TaskID, Billable: in.Billable,
			Date: in.Date, Task: in.Task,
		}
		hours := in.Hours
		existing, qerr := c.TimesheetEntry.Query().Where(entryKey(tenantID, entry)...).First(ctx)
		switch {
		case qerr == nil:
			if in.Add {
				hours = hours.Add(existing.RegularHours)
			}
			// upsertEntryTx writes every hours column: keep what this call does not change.
			entry.OvertimeHours, entry.BreakHours = existing.OvertimeHours.String(), existing.BreakHours.String()
			if entry.Task == "" {
				entry.Task = existing.TaskDescription
			}
		case !ent.IsNotFound(qerr):
			return fmt.Errorf("attendance: load entry: %w", qerr)
		}
		if hours.GreaterThan(MaxEntryHours) {
			return fmt.Errorf("%w: the entry would exceed 24 hours", ErrInvalidEntry)
		}
		entry.RegularHours = hours.Round(2).String()
		var werr error
		row, werr = upsertEntryTx(ctx, c, tenantID, entry)
		return werr
	})
	if err != nil {
		return nil, err
	}
	ts, err := s.getTimesheet(ctx, tenantID, sheet.ID)
	if err != nil {
		return nil, err
	}
	return &LoggedEntry{EmployeeID: in.EmployeeID, Timesheet: ts, Entry: row}, nil
}

// SubmitEmployeeRange submits every draft or rejected timesheet of the employee overlapping
// [from, to].
func (s *Service) SubmitEmployeeRange(ctx context.Context, tenantID, employeeID uuid.UUID, from, to time.Time) ([]*ent.Timesheet, error) {
	sheets, err := s.overlapping(ctx, tenantID, employeeID, from, to)
	if err != nil {
		return nil, fmt.Errorf("attendance: employee timesheets: %w", err)
	}
	var out []*ent.Timesheet
	for _, ts := range sheets {
		if ts.Status != timesheet.StatusDraft && ts.Status != timesheet.StatusRejected {
			continue
		}
		row, err := s.SubmitTimesheet(ctx, tenantID, ts.ID)
		if err != nil {
			return nil, err
		}
		out = append(out, row)
	}
	if len(out) == 0 {
		return nil, ErrNothingToSubmit
	}
	return out, nil
}
