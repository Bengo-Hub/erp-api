package payrollsettings

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/generalhrsettings"
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
// Statutory items the tenant has deliberately disabled (GeneralHRSettings toggles) are
// not resolved at all and are marked in cfg.Disabled — the engine skips them silently.
func (s *Service) BuildEngineConfig(ctx context.Context, tenantID uuid.UUID, period time.Time, recoverAdvances bool) (payrollengine.Config, error) {
	var cfg payrollengine.Config
	cfg.RecoverAdvances = recoverAdvances

	// Tenant statutory toggles: tenant row only, NO system fallback — an opt-out is a
	// tenant business decision, not a KRA default. Missing row => everything enabled.
	toggles, err := s.statutoryToggles(ctx, tenantID)
	if err != nil {
		return cfg, fmt.Errorf("statutory settings: %w", err)
	}
	cfg.Disabled = toggles.disabledComponents()

	if toggles.paye {
		income, err := s.resolveRates(ctx, tenantID, "income", "primary", period, true)
		if err != nil {
			return cfg, fmt.Errorf("income/PAYE: %w", err)
		}
		cfg.Income = income

		// Optional secondary-employment PAYE table (flat top-rate, no relief). Absent for tenants
		// that don't employ secondary staff — secondary employees then fall back to primary bands.
		if sec, e := s.resolveRates(ctx, tenantID, "income", "secondary", period, false); e == nil {
			cfg.IncomeSecondary = sec
		}
	}

	if toggles.nssf {
		nssf, err := s.resolveRates(ctx, tenantID, "deduction", "social_security_fund", period, false)
		if err != nil {
			return cfg, fmt.Errorf("NSSF: %w", err)
		}
		cfg.NSSF = nssf
	}

	if toggles.housingLevy {
		housing, err := s.resolveRates(ctx, tenantID, "deduction", "housing_levy", period, false)
		if err != nil {
			return cfg, fmt.Errorf("housing levy: %w", err)
		}
		cfg.HousingLevy = housing
	}

	// Health: SHIF if effective, else NHIF — config-driven cutover (no hardcoded date).
	if toggles.shif {
		if shif, e := s.resolveRates(ctx, tenantID, "deduction", "shif", period, false); e == nil {
			cfg.SHIF = shif
		}
		if nhif, e := s.resolveRates(ctx, tenantID, "deduction", "nhif", period, false); e == nil {
			cfg.NHIF = nhif
		}
		if cfg.SHIF == nil && cfg.NHIF == nil {
			return cfg, fmt.Errorf("health (SHIF/NHIF): %w", payrollengine.ErrFormulaNotConfigured)
		}
	}

	// NITA (employer-only levy) is best-effort: tenants without a NITA formula are
	// unaffected (no fail-loud) — the levy simply doesn't appear.
	if toggles.nita {
		if nita, e := s.resolveRates(ctx, tenantID, "deduction", "nita", period, false); e == nil {
			cfg.NITA = nita
		}
	}

	// Resolve the deduction ordering from the income formula if present.
	if f, e := s.EffectiveFormula(ctx, tenantID, "income", "primary", period); e == nil && len(f.DeductionOrder) > 0 {
		for _, p := range f.DeductionOrder {
			cfg.DeductionOrder = append(cfg.DeductionOrder, payrollengine.Phase{Name: p.Phase, Components: p.Components})
		}
	}
	return cfg, nil
}

// statutoryToggleSet is the tenant's statutory opt-out state (GeneralHRSettings toggles).
type statutoryToggleSet struct {
	paye, nssf, shif, housingLevy, nita bool
}

// statutoryToggles loads the tenant's statutory toggles. Tenant row ONLY — no system
// fallback: opting out is a tenant business decision, never an inherited default. A
// missing row means all enabled (matches the schema defaults).
func (s *Service) statutoryToggles(ctx context.Context, tenantID uuid.UUID) (statutoryToggleSet, error) {
	all := statutoryToggleSet{paye: true, nssf: true, shif: true, housingLevy: true, nita: true}
	g, err := s.orm.GeneralHRSettings.Query().
		Where(generalhrsettings.TenantID(tenantID)).Only(ctx)
	if ent.IsNotFound(err) {
		return all, nil
	}
	if err != nil {
		return all, err
	}
	return statutoryToggleSet{
		paye:        g.PayeEnabled,
		nssf:        g.NssfEnabled,
		shif:        g.ShifEnabled,
		housingLevy: g.HousingLevyEnabled,
		nita:        g.NitaEnabled,
	}, nil
}

// disabledComponents maps the toggle set onto engine component codes. The SHIF toggle
// covers both SHIF and legacy NHIF (they are the same health contribution).
func (t statutoryToggleSet) disabledComponents() map[string]bool {
	d := map[string]bool{}
	if !t.paye {
		d[payrollengine.CompPAYE] = true
	}
	if !t.nssf {
		d[payrollengine.CompNSSF] = true
	}
	if !t.shif {
		d[payrollengine.CompSHIF] = true
		d[payrollengine.CompNHIF] = true
	}
	if !t.housingLevy {
		d[payrollengine.CompHousingLevy] = true
	}
	if !t.nita {
		d[payrollengine.CompNITA] = true
	}
	if len(d) == 0 {
		return nil // nil map = all enabled; keeps zero-value Config semantics
	}
	return d
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
