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

// RuleInput is the create payload for an attendance rule (decimal fields as strings). Empty
// numeric strings fall back to the tenant attendance settings.
type RuleInput struct {
	Name                       string
	RuleType                   string
	Description                string
	IsActive                   bool
	Priority                   int
	BranchID                   *uuid.UUID
	DepartmentID               *uuid.UUID
	LateThresholdMinutes       int
	LatePenaltyType            string
	LatePenaltyValue           string
	OvertimeThresholdHours     string
	OvertimeRateMultiplier     string
	MaxOvertimeHours           string
	StandardWorkHours          string
	MinWorkHours               string
	MaxWorkHours               string
	ConsecutiveAbsentThreshold *int
	MonthlyAbsentThreshold     *int
	AbsenteeismAction          string
	BreakDurationMinutes       *int
	HolidayPayMultiplier       string
}

// CreateRule inserts a tenant-scoped attendance rule.
func (s *Service) CreateRule(ctx context.Context, tenantID uuid.UUID, in RuleInput) (*ent.AttendanceRule, error) {
	st, err := s.GetSettings(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	dec := func(field, v string, def decimal.Decimal) (decimal.Decimal, error) {
		if v == "" {
			return def, nil
		}
		d, err := decimal.NewFromString(v)
		if err != nil {
			return decimal.Zero, fmt.Errorf("attendance: %s: %w", field, err)
		}
		if d.IsNegative() {
			return decimal.Zero, fmt.Errorf("attendance: %s cannot be negative", field)
		}
		return d, nil
	}
	vals := map[string]decimal.Decimal{}
	for _, f := range []struct {
		name, v string
		def     decimal.Decimal
	}{
		{"late_penalty_value", in.LatePenaltyValue, decimal.Zero},
		{"overtime_threshold_hours", in.OvertimeThresholdHours, st.OTThresholdHours},
		{"overtime_rate_multiplier", in.OvertimeRateMultiplier, st.OTMultiplier},
		{"max_overtime_hours", in.MaxOvertimeHours, st.OTMaxHours},
		{"standard_work_hours", in.StandardWorkHours, st.OTThresholdHours},
		{"min_work_hours", in.MinWorkHours, st.MinWorkHours},
		{"max_work_hours", in.MaxWorkHours, st.OTThresholdHours.Add(st.OTMaxHours)},
		{"holiday_pay_multiplier", in.HolidayPayMultiplier, st.HolidayMultiplier},
	} {
		d, err := dec(f.name, f.v, f.def)
		if err != nil {
			return nil, err
		}
		vals[f.name] = d
	}
	b := s.orm.AttendanceRule.Create().
		SetTenantID(tenantID).SetName(in.Name).
		SetRuleType(attendancerule.RuleType(in.RuleType)).
		SetIsActive(in.IsActive).SetPriority(in.Priority).
		SetNillableBranchID(in.BranchID).SetNillableDepartmentID(in.DepartmentID).
		SetLateThresholdMinutes(in.LateThresholdMinutes).
		SetLatePenaltyValue(vals["late_penalty_value"]).
		SetOvertimeThresholdHours(vals["overtime_threshold_hours"]).
		SetOvertimeRateMultiplier(vals["overtime_rate_multiplier"]).
		SetMaxOvertimeHours(vals["max_overtime_hours"]).
		SetStandardWorkHours(vals["standard_work_hours"]).
		SetMinWorkHours(vals["min_work_hours"]).
		SetMaxWorkHours(vals["max_work_hours"]).
		SetHolidayPayMultiplier(vals["holiday_pay_multiplier"]).
		SetNillableConsecutiveAbsentThreshold(in.ConsecutiveAbsentThreshold).
		SetNillableMonthlyAbsentThreshold(in.MonthlyAbsentThreshold).
		SetNillableBreakDurationMinutes(in.BreakDurationMinutes)
	if in.Description != "" {
		b = b.SetDescription(in.Description)
	}
	if in.LatePenaltyType != "" {
		b = b.SetLatePenaltyType(in.LatePenaltyType)
	}
	if in.AbsenteeismAction != "" {
		b = b.SetAbsenteeismAction(in.AbsenteeismAction)
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
