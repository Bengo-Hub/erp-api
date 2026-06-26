package payrollsettings

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// hundred converts a stored percentage (e.g. 30.00) to a fraction (0.30).
var hundred = decimal.NewFromInt(100)

// defaultEmployerPercentage returns the employer matching fraction (1 == 100%) for a
// statutory category when no explicit PayrollSplitRatio row is configured. NSSF and the
// Housing Levy are matched by the employer; SHIF/NHIF and income tax are employee-only.
func defaultEmployerPercentage(category string) decimal.Decimal {
	switch category {
	case "social_security_fund", "housing_levy":
		return decimal.NewFromInt(1)
	default:
		return decimal.Zero
	}
}

// BuildEngineConfig resolves the tenant-scoped, period-effective rate sets into a
// payrollengine.Config. A missing required statutory formula (income/NSSF/housing, plus
// at least one of SHIF/NHIF) is a fail-loud error — the run aborts (gaps §2.2/§2.4).
func (s *Service) BuildEngineConfig(ctx context.Context, tenantID uuid.UUID, period time.Time, recoverAdvances bool) (payrollengine.Config, error) {
	var cfg payrollengine.Config
	cfg.RecoverAdvances = recoverAdvances

	income, err := s.resolveRates(ctx, tenantID, "income", "primary", period, true)
	if err != nil {
		return cfg, fmt.Errorf("income/PAYE: %w", err)
	}
	cfg.Income = income

	nssf, err := s.resolveRates(ctx, tenantID, "deduction", "social_security_fund", period, false)
	if err != nil {
		return cfg, fmt.Errorf("NSSF: %w", err)
	}
	cfg.NSSF = nssf

	housing, err := s.resolveRates(ctx, tenantID, "deduction", "housing_levy", period, false)
	if err != nil {
		return cfg, fmt.Errorf("housing levy: %w", err)
	}
	cfg.HousingLevy = housing

	// Health: SHIF if effective, else NHIF — config-driven cutover (no hardcoded date).
	if shif, e := s.resolveRates(ctx, tenantID, "deduction", "shif", period, false); e == nil {
		cfg.SHIF = shif
	}
	if nhif, e := s.resolveRates(ctx, tenantID, "deduction", "nhif", period, false); e == nil {
		cfg.NHIF = nhif
	}
	if cfg.SHIF == nil && cfg.NHIF == nil {
		return cfg, fmt.Errorf("health (SHIF/NHIF): %w", payrollengine.ErrFormulaNotConfigured)
	}

	// Resolve the deduction ordering from the income formula if present.
	if f, e := s.EffectiveFormula(ctx, tenantID, "income", "primary", period); e == nil && len(f.DeductionOrder) > 0 {
		for _, p := range f.DeductionOrder {
			cfg.DeductionOrder = append(cfg.DeductionOrder, payrollengine.Phase{Name: p.Phase, Components: p.Components})
		}
	}
	return cfg, nil
}

// resolveRates loads a formula + its items + split ratio and maps them to engine bands.
// withPersonalRelief pulls the income formula's personal_relief into the rate set.
func (s *Service) resolveRates(ctx context.Context, tenantID uuid.UUID, ftype, category string, period time.Time, withPersonalRelief bool) (*payrollengine.FormulaRates, error) {
	f, err := s.EffectiveFormula(ctx, tenantID, ftype, category, period)
	if err != nil {
		return nil, err
	}
	items, err := s.FormulaItems(ctx, f.TenantID, f.ID)
	if err != nil {
		return nil, err
	}
	rates := &payrollengine.FormulaRates{
		EmployeePercentage: decimal.NewFromInt(1),
		// Employer-side default by statutory category when no explicit PayrollSplitRatio row
		// exists: NSSF and Housing Levy are matched 100% by the employer; SHIF/NHIF/PAYE are
		// employee-only. A split row (below) overrides this. Without this, a tenant missing
		// split rows silently reports KES 0 employer contributions (muster roll / GL / P9).
		EmployerPercentage: defaultEmployerPercentage(category),
	}
	for _, it := range items {
		to := it.AmountTo
		if to.IsZero() {
			to = payrollengine.Inf
		}
		rate := it.DeductPercentage.Div(hundred)
		rates.Bands = append(rates.Bands, payrollengine.Band{
			From:   it.AmountFrom,
			To:     to,
			Rate:   rate,
			Amount: it.DeductAmount,
		})
	}
	// Non-income formulas may encode an upper band on the formula itself.
	if ftype != "income" && (f.UpperLimitAmount.GreaterThan(decimal.Zero) || f.UpperLimitPercentage.GreaterThan(decimal.Zero)) {
		upRate := f.UpperLimitPercentage.Div(hundred)
		rates.Bands = append(rates.Bands, payrollengine.Band{
			From:   f.UpperLimit,
			To:     payrollengine.Inf,
			Rate:   upRate,
			Amount: f.UpperLimitAmount,
		})
	}
	if withPersonalRelief {
		rates.PersonalRelief = f.PersonalRelief
	}
	if split, e := s.SplitRatio(ctx, f.TenantID, f.ID); e == nil && split != nil {
		rates.EmployeePercentage = split.EmployeePercentage.Div(hundred)
		rates.EmployerPercentage = split.EmployerPercentage.Div(hundred)
	}
	return rates, nil
}
