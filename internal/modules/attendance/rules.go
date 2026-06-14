package attendance

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerule"
	"github.com/Bengo-Hub/erp-api/internal/ent/offday"
	"github.com/Bengo-Hub/erp-api/internal/ent/shiftrotation"
)

// RuleInput is the create payload for an attendance rule (decimal fields as strings).
type RuleInput struct {
	Name                   string
	RuleType               string
	Description            string
	IsActive               bool
	Priority               int
	LateThresholdMinutes   int
	LatePenaltyType        string
	OvertimeThresholdHours string
	OvertimeRateMultiplier string
	MaxOvertimeHours       string
	StandardWorkHours      string
	MinWorkHours           string
	MaxWorkHours           string
}

// CreateRule inserts a tenant-scoped attendance rule.
func (s *Service) CreateRule(ctx context.Context, tenantID uuid.UUID, in RuleInput) (*ent.AttendanceRule, error) {
	dec := func(s string, def string) (decimal.Decimal, error) {
		if s == "" {
			s = def
		}
		return decimal.NewFromString(s)
	}
	otThr, err := dec(in.OvertimeThresholdHours, "8")
	if err != nil {
		return nil, fmt.Errorf("attendance: overtime_threshold_hours: %w", err)
	}
	otMul, err := dec(in.OvertimeRateMultiplier, "1.5")
	if err != nil {
		return nil, fmt.Errorf("attendance: overtime_rate_multiplier: %w", err)
	}
	maxOT, err := dec(in.MaxOvertimeHours, "4")
	if err != nil {
		return nil, fmt.Errorf("attendance: max_overtime_hours: %w", err)
	}
	std, err := dec(in.StandardWorkHours, "8")
	if err != nil {
		return nil, fmt.Errorf("attendance: standard_work_hours: %w", err)
	}
	minH, err := dec(in.MinWorkHours, "6")
	if err != nil {
		return nil, fmt.Errorf("attendance: min_work_hours: %w", err)
	}
	maxH, err := dec(in.MaxWorkHours, "12")
	if err != nil {
		return nil, fmt.Errorf("attendance: max_work_hours: %w", err)
	}
	b := s.orm.AttendanceRule.Create().
		SetTenantID(tenantID).SetName(in.Name).
		SetRuleType(attendancerule.RuleType(in.RuleType)).
		SetIsActive(in.IsActive).SetPriority(in.Priority).
		SetLateThresholdMinutes(in.LateThresholdMinutes).
		SetOvertimeThresholdHours(otThr).SetOvertimeRateMultiplier(otMul).SetMaxOvertimeHours(maxOT).
		SetStandardWorkHours(std).SetMinWorkHours(minH).SetMaxWorkHours(maxH)
	if in.Description != "" {
		b = b.SetDescription(in.Description)
	}
	if in.LatePenaltyType != "" {
		b = b.SetLatePenaltyType(in.LatePenaltyType)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create rule: %w", err)
	}
	return row, nil
}

// DeleteRule removes a tenant-scoped attendance rule.
func (s *Service) DeleteRule(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.AttendanceRule.Delete().
		Where(attendancerule.TenantID(tenantID), attendancerule.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("attendance: delete rule: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("attendance: rule not found")
	}
	return nil
}

// ---- Shift rotations ----

// ListRotations returns tenant-scoped shift rotations.
func (s *Service) ListRotations(ctx context.Context, tenantID uuid.UUID) ([]*ent.ShiftRotation, error) {
	return s.orm.ShiftRotation.Query().
		Where(shiftrotation.TenantID(tenantID)).
		Order(ent.Desc(shiftrotation.FieldCreatedAt)).All(ctx)
}

// RotationInput is the create payload for a shift rotation.
type RotationInput struct {
	Title         string
	ShiftIDs      []uuid.UUID
	RunDuration   int
	RunUnit       string
	BreakDuration int
	BreakUnit     string
	IsActive      bool
}

// CreateRotation inserts a tenant-scoped shift rotation.
func (s *Service) CreateRotation(ctx context.Context, tenantID uuid.UUID, in RotationInput) (*ent.ShiftRotation, error) {
	b := s.orm.ShiftRotation.Create().
		SetTenantID(tenantID).SetTitle(in.Title).
		SetShiftIds(in.ShiftIDs).
		SetRunDuration(in.RunDuration).SetBreakDuration(in.BreakDuration).
		SetIsActive(in.IsActive)
	if in.RunUnit != "" {
		b = b.SetRunUnit(in.RunUnit)
	}
	if in.BreakUnit != "" {
		b = b.SetBreakUnit(in.BreakUnit)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create rotation: %w", err)
	}
	return row, nil
}

// DeleteRotation removes a tenant-scoped shift rotation.
func (s *Service) DeleteRotation(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.ShiftRotation.Delete().
		Where(shiftrotation.TenantID(tenantID), shiftrotation.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("attendance: delete rotation: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("attendance: rotation not found")
	}
	return nil
}

// ---- Off days ----

// ListOffDays returns tenant-scoped off-days (optionally for one employee).
func (s *Service) ListOffDays(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.OffDay, error) {
	q := s.orm.OffDay.Query().Where(offday.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(offday.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(offday.FieldDate)).All(ctx)
}

// CreateOffDay inserts a tenant-scoped off-day for an employee.
func (s *Service) CreateOffDay(ctx context.Context, tenantID, employeeID uuid.UUID, date time.Time, reason string) (*ent.OffDay, error) {
	b := s.orm.OffDay.Create().SetTenantID(tenantID).SetEmployeeID(employeeID).SetDate(date)
	if reason != "" {
		b = b.SetReason(reason)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create off-day: %w", err)
	}
	return row, nil
}

// DeleteOffDay removes a tenant-scoped off-day.
func (s *Service) DeleteOffDay(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.OffDay.Delete().Where(offday.TenantID(tenantID), offday.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("attendance: delete off-day: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("attendance: off-day not found")
	}
	return nil
}
