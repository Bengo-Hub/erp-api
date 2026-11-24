package attendance

import (
	"context"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftassignment"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftroster"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftrosterslot"
	"github.com/Bengo-Hub/erp-api/internal/ent/staffshiftoverride"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
)

// ---- Rosters ----

// ListRosters returns tenant-scoped shift rosters.
func (s *Service) ListRosters(ctx context.Context, tenantID uuid.UUID) ([]*ent.ShiftRoster, error) {
	return s.orm.ShiftRoster.Query().
		Where(shiftroster.TenantID(tenantID)).
		Order(ent.Asc(shiftroster.FieldName)).All(ctx)
}

// CreateRoster inserts a tenant-scoped shift roster.
func (s *Service) CreateRoster(ctx context.Context, tenantID uuid.UUID, name string, cycleDays int, startDate time.Time) (*ent.ShiftRoster, error) {
	if cycleDays <= 0 {
		cycleDays = 14
	}
	row, err := s.orm.ShiftRoster.Create().
		SetTenantID(tenantID).SetName(name).SetCycleDays(cycleDays).
		SetStartDate(startDate).SetIsActive(true).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create roster: %w", err)
	}
	return row, nil
}

// DeleteRoster removes a tenant-scoped shift roster.
func (s *Service) DeleteRoster(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.ShiftRoster.Delete().Where(shiftroster.TenantID(tenantID), shiftroster.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("attendance: delete roster: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("attendance: roster not found")
	}
	return nil
}

// ---- Roster slots ----

// SlotInput upserts an employee's hours for a roster cycle_day.
type SlotInput struct {
	RosterID   uuid.UUID
	EmployeeID uuid.UUID
	CycleDay   int
	StartTime  string
	EndTime    string
	IsOffDay   bool
}

// UpsertSlot creates/updates a roster slot (unique per roster/employee/cycle_day).
func (s *Service) UpsertSlot(ctx context.Context, tenantID uuid.UUID, in SlotInput) (*ent.ShiftRosterSlot, error) {
	existing, err := s.orm.ShiftRosterSlot.Query().Where(
		shiftrosterslot.TenantID(tenantID),
		shiftrosterslot.RosterID(in.RosterID),
		shiftrosterslot.EmployeeID(in.EmployeeID),
		shiftrosterslot.CycleDay(in.CycleDay),
	).First(ctx)
	if ent.IsNotFound(err) {
		b := s.orm.ShiftRosterSlot.Create().
			SetTenantID(tenantID).SetRosterID(in.RosterID).SetEmployeeID(in.EmployeeID).
			SetCycleDay(in.CycleDay).SetIsOffDay(in.IsOffDay)
		if in.StartTime != "" {
			b = b.SetStartTime(in.StartTime)
		}
		if in.EndTime != "" {
			b = b.SetEndTime(in.EndTime)
		}
		row, cerr := b.Save(ctx)
		if cerr != nil {
			return nil, fmt.Errorf("attendance: create slot: %w", cerr)
		}
		return row, nil
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: slot lookup: %w", err)
	}
	u := existing.Update().SetIsOffDay(in.IsOffDay)
	if in.StartTime != "" {
		u = u.SetStartTime(in.StartTime)
	}
	if in.EndTime != "" {
		u = u.SetEndTime(in.EndTime)
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: update slot: %w", err)
	}
	return row, nil
}

// ListSlots returns the slots for a tenant-scoped roster.
func (s *Service) ListSlots(ctx context.Context, tenantID, rosterID uuid.UUID) ([]*ent.ShiftRosterSlot, error) {
	return s.orm.ShiftRosterSlot.Query().
		Where(shiftrosterslot.TenantID(tenantID), shiftrosterslot.RosterID(rosterID)).
		Order(ent.Asc(shiftrosterslot.FieldCycleDay)).All(ctx)
}

// ---- Assignments ----

// AssignRoster assigns an employee to a roster for a date window (the missing planner link).
func (s *Service) AssignRoster(ctx context.Context, tenantID, employeeID, rosterID uuid.UUID, start time.Time, end *time.Time) (*ent.ShiftAssignment, error) {
	b := s.orm.ShiftAssignment.Create().
		SetTenantID(tenantID).SetEmployeeID(employeeID).SetRosterID(rosterID).
		SetStartDate(start).SetIsActive(true)
	if end != nil {
		b = b.SetEndDate(*end)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: assign roster: %w", err)
	}
	return row, nil
}

// ListAssignments returns tenant-scoped roster assignments (optionally for one employee).
func (s *Service) ListAssignments(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.ShiftAssignment, error) {
	q := s.orm.ShiftAssignment.Query().Where(shiftassignment.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(shiftassignment.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(shiftassignment.FieldStartDate)).All(ctx)
}

// DeleteAssignment removes a tenant-scoped roster assignment.
func (s *Service) DeleteAssignment(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.ShiftAssignment.Delete().
		Where(shiftassignment.ID(id), shiftassignment.TenantID(tenantID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("attendance: delete assignment: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("attendance: assignment not found")
	}
	return nil
}

// ---- Staff shift overrides ----

// OverrideInput is the create payload for a date-specific shift override.
type OverrideInput struct {
	EmployeeID   uuid.UUID
	Date         time.Time
	OverrideType string
	WorkShiftID  *uuid.UUID
	StartTime    string
	EndTime      string
	Reason       string
	Status       string // manager-created -> approved; staff self-submission -> pending
	CreatedBy    *uuid.UUID
}

// validateOverride checks the override type and its times: a manual shift or half day needs a
// start and end time (HH:MM), unless a named work shift supplies them; off duty carries none.
func validateOverride(in *OverrideInput) error {
	in.StartTime, in.EndTime = strings.TrimSpace(in.StartTime), strings.TrimSpace(in.EndTime)
	switch in.OverrideType {
	case "off_duty":
		in.StartTime, in.EndTime, in.WorkShiftID = "", "", nil
		return nil
	case "manual_shift", "half_day":
	default:
		return errors.New("override type must be off duty, manual shift or half day")
	}
	if in.WorkShiftID == nil && (in.StartTime == "" || in.EndTime == "") {
		return errors.New("start and end times are required unless the override is off duty")
	}
	for _, t := range []string{in.StartTime, in.EndTime} {
		if t == "" {
			continue
		}
		if _, err := time.Parse("15:04", t); err != nil {
			if _, err2 := time.Parse("15:04:05", t); err2 != nil {
				return fmt.Errorf("invalid time %q (want HH:MM)", t)
			}
		}
	}
	return nil
}

// CreateOverride inserts a tenant-scoped staff shift override (unique per employee/date).
func (s *Service) CreateOverride(ctx context.Context, tenantID uuid.UUID, in OverrideInput) (*ent.StaffShiftOverride, error) {
	if err := validateOverride(&in); err != nil {
		return nil, err
	}
	status := in.Status
	if status == "" {
		status = "approved"
	}
	b := s.orm.StaffShiftOverride.Create().
		SetTenantID(tenantID).SetEmployeeID(in.EmployeeID).SetDate(in.Date).
		SetOverrideType(staffshiftoverride.OverrideType(in.OverrideType)).
		SetStatus(staffshiftoverride.Status(status))
	if in.StartTime != "" {
		b = b.SetStartTime(in.StartTime)
	}
	if in.EndTime != "" {
		b = b.SetEndTime(in.EndTime)
	}
	if in.Reason != "" {
		b = b.SetReason(in.Reason)
	}
	if in.CreatedBy != nil {
		b = b.SetCreatedBy(*in.CreatedBy)
	}
	if in.WorkShiftID != nil {
		b = b.SetWorkShiftID(*in.WorkShiftID)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create override: %w", err)
	}
	return row, nil
}

// ---- Weekly shift planner (per-cell, drawable roster) ----
//
// The planner is a drawable employee×date grid. Each filled cell is persisted as a
// StaffShiftOverride keyed uniquely on (tenant, employee, date) — clicking a shift onto a
// cell upserts that row with override_type=manual_shift + work_shift_id; clearing deletes it.
// This reuses the existing override store (no new table) and gives a real resolved grid.

// PlannerCellInput upserts one planner cell.
type PlannerCellInput struct {
	EmployeeID  uuid.UUID
	Date        time.Time
	WorkShiftID *uuid.UUID // nil => an explicit off-duty cell
	StartTime   string
	EndTime     string
	CreatedBy   *uuid.UUID
}

// ResolvedCell is a flattened planner cell with the shift name/times resolved for the UI.
type ResolvedCell struct {
	Employee     uuid.UUID  `json:"employee"`
	EmployeeName string     `json:"employee_name,omitempty"`
	Date         string     `json:"date"`
	WorkShiftID  *uuid.UUID `json:"work_shift_id,omitempty"`
	ShiftName    string     `json:"shift_name,omitempty"`
	StartTime    string     `json:"start_time,omitempty"`
	EndTime      string     `json:"end_time,omitempty"`
	IsOff        bool       `json:"is_off"`
	OverrideID   uuid.UUID  `json:"override_id"`
}

// PlannerReason is the reason the weekly shift planner stores on the overrides it writes, so the
// overrides list can tell planner cells from one-off overrides.
const PlannerReason = "Set in shift planner"

// UpsertPlannerCell creates/replaces the cell for (employee, date). work_shift_id nil = off-duty.
func (s *Service) UpsertPlannerCell(ctx context.Context, tenantID uuid.UUID, in PlannerCellInput) (*ent.StaffShiftOverride, error) {
	overrideType := "manual_shift"
	if in.WorkShiftID == nil {
		overrideType = "off_duty"
	}
	existing, err := s.orm.StaffShiftOverride.Query().Where(
		staffshiftoverride.TenantID(tenantID),
		staffshiftoverride.EmployeeID(in.EmployeeID),
		staffshiftoverride.Date(in.Date),
	).First(ctx)
	if ent.IsNotFound(err) {
		return s.CreateOverride(ctx, tenantID, OverrideInput{
			EmployeeID: in.EmployeeID, Date: in.Date, OverrideType: overrideType,
			WorkShiftID: in.WorkShiftID, StartTime: in.StartTime, EndTime: in.EndTime,
			Reason: PlannerReason, Status: "approved", CreatedBy: in.CreatedBy,
		})
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: planner cell lookup: %w", err)
	}
	u := existing.Update().
		SetOverrideType(staffshiftoverride.OverrideType(overrideType)).
		SetStatus(staffshiftoverride.StatusApproved).
		SetReason(PlannerReason)
	if in.WorkShiftID != nil {
		u = u.SetWorkShiftID(*in.WorkShiftID)
	} else {
		u = u.ClearWorkShiftID()
	}
	if in.StartTime != "" {
		u = u.SetStartTime(in.StartTime)
	} else {
		u = u.ClearStartTime()
	}
	if in.EndTime != "" {
		u = u.SetEndTime(in.EndTime)
	} else {
		u = u.ClearEndTime()
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: update planner cell: %w", err)
	}
	return row, nil
}

// ClearPlannerCell deletes the cell for (employee, date), if any.
func (s *Service) ClearPlannerCell(ctx context.Context, tenantID, employeeID uuid.UUID, date time.Time) error {
	_, err := s.orm.StaffShiftOverride.Delete().Where(
		staffshiftoverride.TenantID(tenantID),
		staffshiftoverride.EmployeeID(employeeID),
		staffshiftoverride.Date(date),
	).Exec(ctx)
	if err != nil {
		return fmt.Errorf("attendance: clear planner cell: %w", err)
	}
	return nil
}

// ResolvePlanner returns the filled planner cells in [from, to], with shift name/times +
// employee names resolved for direct rendering.
func (s *Service) ResolvePlanner(ctx context.Context, tenantID uuid.UUID, from, to time.Time) ([]ResolvedCell, error) {
	rows, err := s.orm.StaffShiftOverride.Query().Where(
		staffshiftoverride.TenantID(tenantID),
		staffshiftoverride.DateGTE(from),
		staffshiftoverride.DateLTE(to),
	).Order(ent.Asc(staffshiftoverride.FieldDate)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: resolve planner: %w", err)
	}

	// Resolve shift names/times in one batch.
	shiftIDs := make([]uuid.UUID, 0, len(rows))
	empIDs := make([]uuid.UUID, 0, len(rows))
	for _, r := range rows {
		if r.WorkShiftID != nil {
			shiftIDs = append(shiftIDs, *r.WorkShiftID)
		}
		empIDs = append(empIDs, r.EmployeeID)
	}
	shifts := map[uuid.UUID]*ent.WorkShift{}
	if len(shiftIDs) > 0 {
		ss, serr := s.orm.WorkShift.Query().Where(
			workshift.TenantID(tenantID), workshift.IDIn(shiftIDs...),
		).All(ctx)
		if serr == nil {
			for _, sh := range ss {
				shifts[sh.ID] = sh
			}
		}
	}
	names := s.employeeNames(ctx, tenantID, empIDs)

	out := make([]ResolvedCell, 0, len(rows))
	for _, r := range rows {
		c := ResolvedCell{
			Employee: r.EmployeeID, EmployeeName: names[r.EmployeeID],
			Date: r.Date.Format("2006-01-02"), WorkShiftID: r.WorkShiftID,
			IsOff: r.OverrideType == staffshiftoverride.OverrideTypeOffDuty, OverrideID: r.ID,
		}
		if r.StartTime != nil {
			c.StartTime = *r.StartTime
		}
		if r.EndTime != nil {
			c.EndTime = *r.EndTime
		}
		if r.WorkShiftID != nil {
			if sh, ok := shifts[*r.WorkShiftID]; ok {
				c.ShiftName = sh.Name
				if c.StartTime == "" && sh.StartTime != nil {
					c.StartTime = *sh.StartTime
				}
				if c.EndTime == "" && sh.EndTime != nil {
					c.EndTime = *sh.EndTime
				}
			}
		}
		if c.IsOff && c.ShiftName == "" {
			c.ShiftName = "Off"
		}
		out = append(out, c)
	}
	return out, nil
}

// ListOverrides returns tenant-scoped overrides (optionally for one employee).
func (s *Service) ListOverrides(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.StaffShiftOverride, error) {
	q := s.orm.StaffShiftOverride.Query().Where(staffshiftoverride.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(staffshiftoverride.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(staffshiftoverride.FieldDate)).All(ctx)
}

// UpdateOverride edits a tenant-scoped override with the create validation. A row the weekly
// shift planner wrote keeps its work shift while it stays a manual shift, so the planner cell
// still shows that shift; turning it into off duty or a half day drops the shift. A blank status
// keeps the current one. The planner reads the same rows, so the edit shows there at once.
func (s *Service) UpdateOverride(ctx context.Context, tenantID, id uuid.UUID, in OverrideInput) (*ent.StaffShiftOverride, error) {
	existing, err := s.orm.StaffShiftOverride.Query().
		Where(staffshiftoverride.TenantID(tenantID), staffshiftoverride.ID(id)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, fmt.Errorf("shift override %w", ErrNotFound)
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: load override: %w", err)
	}
	in.WorkShiftID = nil
	if in.OverrideType == "manual_shift" {
		in.WorkShiftID = existing.WorkShiftID
	}
	if err := validateOverride(&in); err != nil {
		return nil, err
	}
	u := existing.Update().
		SetEmployeeID(in.EmployeeID).SetDate(in.Date).
		SetOverrideType(staffshiftoverride.OverrideType(in.OverrideType))
	if in.Status != "" {
		u = u.SetStatus(staffshiftoverride.Status(in.Status))
	}
	if in.WorkShiftID != nil {
		u = u.SetWorkShiftID(*in.WorkShiftID)
	} else {
		u = u.ClearWorkShiftID()
	}
	if in.StartTime != "" {
		u = u.SetStartTime(in.StartTime)
	} else {
		u = u.ClearStartTime()
	}
	if in.EndTime != "" {
		u = u.SetEndTime(in.EndTime)
	} else {
		u = u.ClearEndTime()
	}
	if r := strings.TrimSpace(in.Reason); r != "" {
		u = u.SetReason(r)
	} else {
		u = u.ClearReason()
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: update override: %w", err)
	}
	return row, nil
}

// DeleteOverride removes a tenant-scoped override. Planner cells are these same rows, so
// deleting one written by the weekly shift planner clears that cell.
func (s *Service) DeleteOverride(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.StaffShiftOverride.Delete().
		Where(staffshiftoverride.TenantID(tenantID), staffshiftoverride.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("attendance: delete override: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("shift override %w", ErrNotFound)
	}
	return nil
}
