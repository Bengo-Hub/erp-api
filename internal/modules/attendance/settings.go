package attendance

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
)

// SettingsKey is the AppSetting key holding a tenant's attendance settings.
const SettingsKey = "hrm.attendance_settings"

// Geo modes for self clock-in outside every work site.
const (
	GeoModeOff   = "off"   // no fence check
	GeoModeFlag  = "flag"  // accept and flag the punch for HR review
	GeoModeBlock = "block" // refuse the punch
)

// Settings is the tenant's attendance policy. Every threshold the attendance code uses comes
// from here (or from a more specific attendance rule), never from a constant in code.
type Settings struct {
	GeoMode                string          `json:"geo_mode"`
	GeoToleranceM          float64         `json:"geo_tolerance_m"`
	RequirePhoto           bool            `json:"require_photo"`
	DeviceOnlineMinutes    int             `json:"device_online_minutes"`
	AutoAbsentEnabled      bool            `json:"auto_absent_enabled"`
	AutoAbsentTime         string          `json:"auto_absent_time"`
	OTThresholdHours       decimal.Decimal `json:"ot_threshold_hours"`
	OTMaxHours             decimal.Decimal `json:"ot_max_hours"`
	MinWorkHours           decimal.Decimal `json:"min_work_hours"`
	OTMultiplier           decimal.Decimal `json:"ot_multiplier"`
	HolidayMultiplier      decimal.Decimal `json:"holiday_multiplier"`
	EarlyLeaveGraceMinutes int             `json:"early_leave_grace_minutes"`
	PunchPairWindowMinutes int             `json:"punch_pair_window_minutes"`
	// OvernightCutoffHours is how long after a night shift's end a punch still belongs to the
	// shift's start day.
	OvernightCutoffHours int `json:"overnight_cutoff_hours"`
	// DefaultWorkingDays applies to a shift that has no per-day schedule.
	DefaultWorkingDays []string `json:"default_working_days"`
	// PayrollOvertimeEnabled pays overtime and holiday work as earnings in the payroll run.
	PayrollOvertimeEnabled bool `json:"payroll_overtime_enabled"`
	// OvertimeRequiresApproval pays at most the approved overtime request hours for a day.
	OvertimeRequiresApproval bool `json:"overtime_requires_approval"`
	// StandardMonthlyHours turns a monthly salary into an hourly rate when the employee's
	// shift does not give weekly hours.
	StandardMonthlyHours decimal.Decimal `json:"standard_monthly_hours"`
}

// DefaultSettings is what a tenant gets until HR saves its own.
func DefaultSettings() Settings {
	return Settings{
		GeoMode:                GeoModeFlag,
		GeoToleranceM:          50,
		DeviceOnlineMinutes:    3,
		AutoAbsentTime:         "23:00",
		OTThresholdHours:       decimal.NewFromInt(8),
		OTMaxHours:             decimal.NewFromInt(4),
		MinWorkHours:           decimal.NewFromInt(6),
		OTMultiplier:           decimal.NewFromFloat(1.5),
		HolidayMultiplier:      decimal.NewFromInt(2),
		EarlyLeaveGraceMinutes: 10,
		PunchPairWindowMinutes: 2,
		OvernightCutoffHours:   4,
		DefaultWorkingDays:     []string{"Monday", "Tuesday", "Wednesday", "Thursday", "Friday"},
		StandardMonthlyHours:   decimal.NewFromInt(195), // 45 hours a week, 52 weeks over 12 months
	}
}

// Validate checks settings before they are saved.
func (st Settings) Validate() error {
	switch st.GeoMode {
	case GeoModeOff, GeoModeFlag, GeoModeBlock:
	default:
		return errors.New("geo_mode must be off, flag or block")
	}
	if st.GeoToleranceM < 0 || st.DeviceOnlineMinutes < 1 {
		return errors.New("geo_tolerance_m cannot be negative and device_online_minutes must be at least 1")
	}
	if _, err := time.Parse("15:04", st.AutoAbsentTime); err != nil {
		return errors.New("auto_absent_time must be HH:MM")
	}
	if !st.StandardMonthlyHours.IsPositive() {
		return errors.New("standard_monthly_hours must be above 0")
	}
	for _, d := range []decimal.Decimal{st.OTThresholdHours, st.OTMaxHours, st.MinWorkHours, st.OTMultiplier, st.HolidayMultiplier} {
		if d.IsNegative() {
			return errors.New("hours and multipliers cannot be negative")
		}
	}
	if st.EarlyLeaveGraceMinutes < 0 || st.PunchPairWindowMinutes < 0 || st.OvernightCutoffHours < 0 || st.OvernightCutoffHours > 12 {
		return errors.New("grace and window minutes cannot be negative; overnight_cutoff_hours is 0 to 12")
	}
	valid := map[string]bool{}
	for _, d := range weekdayToScheduleDay {
		valid[d] = true
	}
	for _, d := range st.DefaultWorkingDays {
		if !valid[d] {
			return fmt.Errorf("default_working_days: %q is not a weekday name", d)
		}
	}
	return nil
}

// GetSettings returns the tenant's attendance settings merged over the defaults, so a key
// added later still has a value for tenants that saved before it existed.
func (s *Service) GetSettings(ctx context.Context, tenantID uuid.UUID) (Settings, error) {
	st := DefaultSettings()
	row, err := s.orm.AppSetting.Query().
		Where(appsetting.TenantID(tenantID), appsetting.AppKey(SettingsKey)).Only(ctx)
	if ent.IsNotFound(err) {
		return st, nil
	}
	if err != nil {
		return st, fmt.Errorf("attendance: load settings: %w", err)
	}
	if row.Value != "" {
		if err := json.Unmarshal([]byte(row.Value), &st); err != nil {
			return DefaultSettings(), fmt.Errorf("attendance: decode settings: %w", err)
		}
	}
	return st, nil
}

// SaveSettings applies a partial JSON patch over the current settings, validates and stores it.
func (s *Service) SaveSettings(ctx context.Context, tenantID uuid.UUID, patch json.RawMessage) (Settings, error) {
	st, err := s.GetSettings(ctx, tenantID)
	if err != nil {
		return st, err
	}
	if err := json.Unmarshal(patch, &st); err != nil {
		return st, fmt.Errorf("invalid settings: %w", err)
	}
	if err := st.Validate(); err != nil {
		return st, err
	}
	raw, err := json.Marshal(st)
	if err != nil {
		return st, err
	}
	err = s.orm.AppSetting.Create().
		SetTenantID(tenantID).SetAppKey(SettingsKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).
		UpdateNewValues().Exec(ctx)
	if err != nil {
		return st, fmt.Errorf("attendance: save settings: %w", err)
	}
	return st, nil
}

// tenantsWithSettings lists tenants that saved attendance settings, with the decoded value.
// The nightly jobs use it to find tenants that switched auto-absent on.
func (s *Service) tenantsWithSettings(ctx context.Context) (map[uuid.UUID]Settings, error) {
	rows, err := s.orm.AppSetting.Query().
		Where(appsetting.AppKey(SettingsKey), appsetting.TenantIDNotNil()).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("attendance: list settings: %w", err)
	}
	out := make(map[uuid.UUID]Settings, len(rows))
	for _, r := range rows {
		st := DefaultSettings()
		if r.Value != "" && json.Unmarshal([]byte(r.Value), &st) != nil {
			continue
		}
		out[*r.TenantID] = st
	}
	return out, nil
}
