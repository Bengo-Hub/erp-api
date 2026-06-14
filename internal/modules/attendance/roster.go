package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftassignment"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftroster"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftrosterslot"
	"github.com/Bengo-Hub/erp-api/internal/ent/staffshiftoverride"
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

// ---- Staff shift overrides ----

// OverrideInput is the create payload for a date-specific shift override.
type OverrideInput struct {
	EmployeeID   uuid.UUID
	Date         time.Time
	OverrideType string
	StartTime    string
	EndTime      string
	Reason       string
	Status       string // manager-created -> approved; staff self-submission -> pending
	CreatedBy    *uuid.UUID
}

// CreateOverride inserts a tenant-scoped staff shift override (unique per employee/date).
func (s *Service) CreateOverride(ctx context.Context, tenantID uuid.UUID, in OverrideInput) (*ent.StaffShiftOverride, error) {
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
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create override: %w", err)
	}
	return row, nil
}

// ListOverrides returns tenant-scoped overrides (optionally for one employee).
func (s *Service) ListOverrides(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.StaffShiftOverride, error) {
	q := s.orm.StaffShiftOverride.Query().Where(staffshiftoverride.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(staffshiftoverride.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(staffshiftoverride.FieldDate)).All(ctx)
}
