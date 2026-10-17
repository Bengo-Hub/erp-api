package attendance

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/attendancerule"
	"github.com/Bengo-Hub/erp-api/internal/ent/esssettings"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshiftschedule"
)

// Service holds attendance CRUD + late/overtime computation. All queries are tenant-scoped.
type Service struct {
	orm *ent.Client
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// ---- Work shifts ----

// ListShifts returns tenant-scoped work shifts.
func (s *Service) ListShifts(ctx context.Context, tenantID uuid.UUID) ([]*ent.WorkShift, error) {
	return s.orm.WorkShift.Query().
		Where(workshift.TenantID(tenantID)).
		Order(ent.Asc(workshift.FieldCreatedAt)).All(ctx)
}

// ShiftInput is the create/update payload for a work shift.
type ShiftInput struct {
	Name              string
	StartTime         string
	EndTime           string
	GraceMinutes      int
	TotalHoursPerWeek string
}

// CreateShift inserts a tenant-scoped work shift.
func (s *Service) CreateShift(ctx context.Context, tenantID uuid.UUID, in ShiftInput) (*ent.WorkShift, error) {
	b := s.orm.WorkShift.Create().SetTenantID(tenantID).SetName(in.Name).SetGraceMinutes(in.GraceMinutes)
	if in.StartTime != "" {
		b = b.SetStartTime(in.StartTime)
	}
	if in.EndTime != "" {
		b = b.SetEndTime(in.EndTime)
	}
	if in.TotalHoursPerWeek != "" {
		d, err := parseDecimal(in.TotalHoursPerWeek)
		if err != nil {
			return nil, fmt.Errorf("attendance: total_hours_per_week: %w", err)
		}
		b = b.SetTotalHoursPerWeek(d)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: create shift: %w", err)
	}
	return row, nil
}

// DeleteShift removes a tenant-scoped work shift.
func (s *Service) DeleteShift(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.WorkShift.Delete().Where(workshift.TenantID(tenantID), workshift.ID(id)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("attendance: delete shift: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("attendance: shift not found")
	}
	return nil
}

// EnsureDefaultShift seeds a single default "Regular" shift per tenant if none exists. This
// replaces the per-request DefaultShiftMiddleware — call once per tenant (on first
// shift access / tenant onboarding), not per request.
func (s *Service) EnsureDefaultShift(ctx context.Context, tenantID uuid.UUID) (*ent.WorkShift, error) {
	existing, err := s.orm.WorkShift.Query().
		Where(workshift.TenantID(tenantID), workshift.IsDefault(true)).First(ctx)
	if err == nil {
		return existing, nil
	}
	if !ent.IsNotFound(err) {
		return nil, fmt.Errorf("attendance: default shift lookup: %w", err)
	}
	hours, _ := parseDecimal("40.00")
	row, err := s.orm.WorkShift.Create().
		SetTenantID(tenantID).SetName("Regular").
		SetStartTime("08:00").SetEndTime("17:00").
		SetGraceMinutes(15).SetTotalHoursPerWeek(hours).SetIsDefault(true).Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: seed default shift: %w", err)
	}
	return row, nil
}

// ---- Shift schedules (per-day) ----

// ListSchedules returns the per-day schedule rows for a tenant-scoped work shift.
func (s *Service) ListSchedules(ctx context.Context, tenantID, shiftID uuid.UUID) ([]*ent.WorkShiftSchedule, error) {
	return s.orm.WorkShiftSchedule.Query().
		Where(workshiftschedule.TenantID(tenantID), workshiftschedule.WorkShiftID(shiftID)).All(ctx)
}

// ScheduleInput upserts a per-day schedule for a shift.
type ScheduleInput struct {
	Day          string
	StartTime    string
	EndTime      string
	BreakHours   string
	IsWorkingDay bool
}

// UpsertSchedule creates/updates the schedule row for (shift, day).
func (s *Service) UpsertSchedule(ctx context.Context, tenantID, shiftID uuid.UUID, in ScheduleInput) (*ent.WorkShiftSchedule, error) {
	brk, err := parseDecimalDefault(in.BreakHours)
	if err != nil {
		return nil, fmt.Errorf("attendance: break_hours: %w", err)
	}
	existing, err := s.orm.WorkShiftSchedule.Query().Where(
		workshiftschedule.TenantID(tenantID),
		workshiftschedule.WorkShiftID(shiftID),
		workshiftschedule.DayEQ(workshiftschedule.Day(in.Day)),
	).First(ctx)
	if ent.IsNotFound(err) {
		return s.orm.WorkShiftSchedule.Create().
			SetTenantID(tenantID).SetWorkShiftID(shiftID).
			SetDay(workshiftschedule.Day(in.Day)).
			SetStartTime(in.StartTime).SetEndTime(in.EndTime).
			SetBreakHours(brk).SetIsWorkingDay(in.IsWorkingDay).Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: schedule lookup: %w", err)
	}
	return existing.Update().
		SetStartTime(in.StartTime).SetEndTime(in.EndTime).
		SetBreakHours(brk).SetIsWorkingDay(in.IsWorkingDay).Save(ctx)
}

// ---- Attendance rules ----

// ListRules returns tenant-scoped attendance rules (priority-desc).
func (s *Service) ListRules(ctx context.Context, tenantID uuid.UUID) ([]*ent.AttendanceRule, error) {
	return s.orm.AttendanceRule.Query().
		Where(attendancerule.TenantID(tenantID)).
		Order(ent.Desc(attendancerule.FieldPriority)).All(ctx)
}

// activeOvertimeRule returns the highest-priority active overtime_policy rule for a tenant.
func (s *Service) activeOvertimeRule(ctx context.Context, tenantID uuid.UUID) (*ent.AttendanceRule, error) {
	rule, err := s.orm.AttendanceRule.Query().Where(
		attendancerule.TenantID(tenantID),
		attendancerule.IsActive(true),
		attendancerule.RuleTypeEQ(attendancerule.RuleTypeOvertimePolicy),
	).Order(ent.Desc(attendancerule.FieldPriority)).First(ctx)
	if ent.IsNotFound(err) {
		return nil, nil
	}
	if err != nil {
		return nil, fmt.Errorf("attendance: overtime rule: %w", err)
	}
	return rule, nil
}

// ---- ESS settings (per-tenant) ----

// GetESSSettings returns the tenant's ESS settings, creating defaults on first access
// (per-tenant, not a global singleton).
func (s *Service) GetESSSettings(ctx context.Context, tenantID uuid.UUID) (*ent.ESSSettings, error) {
	row, err := s.orm.ESSSettings.Query().Where(esssettings.TenantID(tenantID)).First(ctx)
	if err == nil {
		return row, nil
	}
	if !ent.IsNotFound(err) {
		return nil, fmt.Errorf("attendance: ess lookup: %w", err)
	}
	return s.orm.ESSSettings.Create().SetTenantID(tenantID).Save(ctx)
}

// UpdateESSSettings applies a partial update to the tenant's ESS settings (booleans/ints
// supplied as a sparse map). Unknown keys are ignored.
func (s *Service) UpdateESSSettings(ctx context.Context, tenantID uuid.UUID, patch map[string]any) (*ent.ESSSettings, error) {
	row, err := s.GetESSSettings(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	u := row.Update()
	boolSetters := map[string]func(bool) *ent.ESSSettingsUpdateOne{
		"enable_shift_based_restrictions":        u.SetEnableShiftBasedRestrictions,
		"allow_payslip_view":                     u.SetAllowPayslipView,
		"allow_leave_application":                u.SetAllowLeaveApplication,
		"allow_timesheet_application":            u.SetAllowTimesheetApplication,
		"allow_overtime_application":             u.SetAllowOvertimeApplication,
		"allow_advance_salary_application":       u.SetAllowAdvanceSalaryApplication,
		"allow_losses_damage_submission":         u.SetAllowLossesDamageSubmission,
		"allow_expense_claims_application":        u.SetAllowExpenseClaimsApplication,
		"require_password_change_on_first_login": u.SetRequirePasswordChangeOnFirstLogin,
		"allow_weekend_login":                    u.SetAllowWeekendLogin,
	}
	for k, setter := range boolSetters {
		if v, ok := patch[k].(bool); ok {
			setter(v)
		}
	}
	intSetters := map[string]func(int) *ent.ESSSettingsUpdateOne{
		"session_timeout_minutes":          u.SetSessionTimeoutMinutes,
		"max_failed_login_attempts":        u.SetMaxFailedLoginAttempts,
		"account_lockout_duration_minutes": u.SetAccountLockoutDurationMinutes,
	}
	for k, setter := range intSetters {
		if v, ok := patch[k].(float64); ok {
			setter(int(v))
		}
	}
	saved, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: update ess: %w", err)
	}
	return saved, nil
}
