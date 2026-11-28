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

// BuildEngineConfig resolves the period-effective rate sets a tenant uses (its own versions,
// else the platform defaults) into a payrollengine.Config. All formulas, bands and splits are
// read in three queries for the whole run. A missing required statutory formula (income, NSSF,
// housing, plus at least one of SHIF/NHIF) is a fail-loud error and the run aborts.
// Statutory items the tenant has deliberately disabled (GeneralHRSettings toggles) are
// not resolved at all and are marked in cfg.Disabled; the engine skips them silently.
func (s *Service) BuildEngineConfig(ctx context.Context, tenantID uuid.UUID, period time.Time, recoverAdvances bool) (payrollengine.Config, error) {
	var cfg payrollengine.Config
	cfg.RecoverAdvances = recoverAdvances

	// Tenant statutory toggles: tenant row only, NO platform fallback. An opt-out is a
	// tenant business decision, not a KRA default. Missing row => everything enabled.
	toggles, err := s.statutoryToggles(ctx, tenantID)
	if err != nil {
		return cfg, fmt.Errorf("statutory settings: %w", err)
	}
	cfg.Disabled = toggles.disabledComponents()

	// Employment Act s.19 limits on what deductions may take (platform data, tenant override).
	limits, err := s.DeductionLimitsFor(ctx, tenantID)
	if err != nil {
		return cfg, fmt.Errorf("deduction limits: %w", err)
	}
	cfg.MaxDeductionShare, cfg.LoanShare = limits.MaxShare, limits.LoanShare

	set, err := s.loadFormulaSet(ctx, tenantID)
	if err != nil {
		return cfg, fmt.Errorf("formulas: %w", err)
	}
	type want struct {
		ftype, category string
		required        bool
		target          **payrollengine.FormulaRates
		label           string
	}
	var wants []want
	if toggles.paye {
		wants = append(wants,
			want{"income", "primary", true, &cfg.Income, "income/PAYE"},
			// Optional secondary-employment PAYE table: secondary employees fall back to the
			// primary bands without relief when it is absent.
			want{"income", "secondary", false, &cfg.IncomeSecondary, ""})
	}
	if toggles.nssf {
		wants = append(wants, want{"deduction", "social_security_fund", true, &cfg.NSSF, "NSSF"})
	}
	if toggles.housingLevy {
		wants = append(wants, want{"deduction", "housing_levy", true, &cfg.HousingLevy, "housing levy"})
	}
	// Health: SHIF if effective, else NHIF; config-driven cutover (no hardcoded date).
	if toggles.shif {
		wants = append(wants,
			want{"deduction", "shif", false, &cfg.SHIF, ""},
			want{"deduction", "nhif", false, &cfg.NHIF, ""})
	}
	// NITA (employer-only levy) is best-effort: no formula, no levy line.
	if toggles.nita {
		wants = append(wants, want{"deduction", "nita", false, &cfg.NITA, ""})
	}

	chosen := make([]*ent.PayrollFormula, len(wants))
	ids := make([]uuid.UUID, 0, len(wants))
	for i, w := range wants {
		f := set.effective(w.ftype, w.category, period)
		if f == nil {
			if w.required {
				return cfg, fmt.Errorf("%s: %w", w.label, payrollengine.ErrFormulaNotConfigured)
			}
			continue
		}
		chosen[i] = f
		ids = append(ids, f.ID)
	}
	items, splits, err := s.formulaBands(ctx, tenantID, ids)
	if err != nil {
		return cfg, fmt.Errorf("formula bands: %w", err)
	}
	for i, w := range wants {
		if f := chosen[i]; f != nil {
			rates := ratesFrom(f, items[f.ID], splits[f.ID])
			// A tenant version that records no minimum (customised before minimums existed)
			// inherits the platform version's; a recorded value, zero included, is its own choice.
			if !hasMinimumContribution(f) && f.TenantID == tenantID {
				k := formulaKey{w.ftype, w.category}
				rates.MinimumContribution = FormulaMinimumContribution(resolveEffective(nil, set.platform[k], period))
			}
			*w.target = rates
		}
	}
	if toggles.shif && cfg.SHIF == nil && cfg.NHIF == nil {
		return cfg, fmt.Errorf("health (SHIF/NHIF): %w", payrollengine.ErrFormulaNotConfigured)
	}

	// Per diem tax-free limit and fringe benefit tax: dated platform rules a tenant may override.
	// Missing rules leave per diem wholly non-taxable and charge no FBT.
	// Only a version actually in force for the month counts: a rule that starts later never
	// reaches back to an earlier month.
	if f := set.inForce(FormulaTypeReliefAllowance, FormulaCategoryPerDiem, period); f != nil {
		cfg.PerDiemDailyExempt = metaDecimal(f.Metadata[MetaDailyExempt])
	}
	if f := set.inForce(FormulaTypeFBT, FormulaCategoryFBT, period); f != nil {
		cfg.FBT = &payrollengine.FBTRates{
			TaxRate:    metaDecimal(f.Metadata[MetaFBTTaxRate]),
			MarketRate: metaDecimal(f.Metadata[MetaMarketInterestRate]),
		}
	}

	// Resolve the deduction ordering from the income formula if present.
	if f := set.effective("income", "primary", period); f != nil && len(f.DeductionOrder) > 0 {
		for _, p := range f.DeductionOrder {
			cfg.DeductionOrder = append(cfg.DeductionOrder, payrollengine.Phase{Name: p.Phase, Components: p.Components})
		}
	}

	// KRA reliefs: the tenant's resolved reliefs (its own choices over the platform defaults).
	reliefs, err := s.ResolveReliefs(ctx, tenantID)
	if err != nil {
		return cfg, fmt.Errorf("reliefs: %w", err)
	}
	applyReliefs(reliefs, &cfg)
	return cfg, nil
}

// applyReliefs maps the active resolved reliefs onto the engine relief caps. Personal relief is
// carried by the income formula; a tenant that switched the Personal Relief off gets none.
func applyReliefs(reliefs []ResolvedRelief, cfg *payrollengine.Config) {
	for _, r := range reliefs {
		switch r.Key {
		case reliefPersonal:
			if !r.IsActive && cfg.Income != nil {
				inc := *cfg.Income
				inc.PersonalRelief = decimal.Zero
				cfg.Income = &inc
			}
			continue
		}
		if !r.IsActive {
			continue
		}
		switch r.Key {
		case reliefInsurance:
			cfg.InsuranceReliefRate = r.Percentage.Div(hundred)
			cfg.InsuranceReliefCap = r.FixedLimit
		case reliefPension:
			cfg.PensionReliefCap = r.FixedLimit
		case reliefMortgage:
			cfg.MortgageReliefCap = r.FixedLimit
		case reliefDisability:
			cfg.DisabilityExemptAmount = r.FixedLimit
		case reliefPostRetirement:
			cfg.PostRetirementMedicalCap = r.FixedLimit
		case reliefNonCash:
			// The statutory treatment: benefits are pay in kind (never taken off cash pay) and
			// taxed once they reach the threshold.
			cfg.NonCashAsTaxable = true
			cfg.NonCashTaxThreshold = r.FixedLimit
		case reliefMeals:
			cfg.MealsMonthlyExemption = r.FixedLimit
		}
	}
}

// statutoryToggleSet is the tenant's statutory opt-out state (GeneralHRSettings toggles).
type statutoryToggleSet struct {
	paye, nssf, shif, housingLevy, nita bool
}

// allStatutoryOn is the default: every statutory deduction applies.
var allStatutoryOn = statutoryToggleSet{paye: true, nssf: true, shif: true, housingLevy: true, nita: true}

// statutoryToggles loads the tenant's statutory toggles. Tenant row ONLY, no platform
// fallback: opting out is a tenant business decision, never an inherited default. A
// missing row means all enabled (matches the schema defaults).
func (s *Service) statutoryToggles(ctx context.Context, tenantID uuid.UUID) (statutoryToggleSet, error) {
	g, err := s.orm.GeneralHRSettings.Query().
		Where(generalhrsettings.TenantID(tenantID)).Only(ctx)
	if ent.IsNotFound(err) {
		return allStatutoryOn, nil
	}
	if err != nil {
		return allStatutoryOn, err
	}
	return statutoryToggleSet{
		paye:        g.PayeEnabled,
		nssf:        g.NssfEnabled,
		shif:        g.ShifEnabled,
		housingLevy: g.HousingLevyEnabled,
		nita:        g.NitaEnabled,
	}, nil
}

// StatutoryEnabled reports whether the tenant applies a statutory component (an engine Comp*
// code such as payrollengine.CompNITA). Reports use it so they follow the same toggles as runs.
func (s *Service) StatutoryEnabled(ctx context.Context, tenantID uuid.UUID, comp string) (bool, error) {
	t, err := s.statutoryToggles(ctx, tenantID)
	if err != nil {
		return false, err
	}
	return t.enabled(comp), nil
}

// enabled reports the toggle that governs a statutory component code.
func (t statutoryToggleSet) enabled(comp string) bool {
	switch comp {
	case payrollengine.CompPAYE:
		return t.paye
	case payrollengine.CompNSSF:
		return t.nssf
	case payrollengine.CompSHIF, payrollengine.CompNHIF:
		return t.shif
	case payrollengine.CompHousingLevy:
		return t.housingLevy
	case payrollengine.CompNITA:
		return t.nita
	}
	return true
}

// disabledComponents maps the toggle set onto engine component codes. The SHIF toggle
// covers both SHIF and legacy NHIF (they are the same health contribution).
func (t statutoryToggleSet) disabledComponents() map[string]bool {
	d := map[string]bool{}
	for _, c := range []string{payrollengine.CompPAYE, payrollengine.CompNSSF, payrollengine.CompSHIF,
		payrollengine.CompNHIF, payrollengine.CompHousingLevy, payrollengine.CompNITA} {
		if !t.enabled(c) {
			d[c] = true
		}
	}
	if len(d) == 0 {
		return nil // nil map = all enabled; keeps zero-value Config semantics
	}
	return d
}

// ratesFrom maps a formula, its bands and its split onto an engine rate set.
func ratesFrom(f *ent.PayrollFormula, items []*ent.PayrollFormulaItem, split *ent.PayrollSplitRatio) *payrollengine.FormulaRates {
	rates := &payrollengine.FormulaRates{
		EmployeePercentage: decimal.NewFromInt(1),
		// Employer-side default by statutory category when no explicit PayrollSplitRatio row
		// exists: NSSF and Housing Levy are matched 100% by the employer; SHIF/NHIF/PAYE are
		// employee-only. A split row (below) overrides this. Without this, a tenant missing
		// split rows silently reports KES 0 employer contributions (muster roll / GL / P9).
		EmployerPercentage: defaultEmployerPercentage(f.Category),
	}
	for _, it := range items {
		to := it.AmountTo
		if to.IsZero() {
			to = payrollengine.Inf
		}
		rates.Bands = append(rates.Bands, payrollengine.Band{
			From:   it.AmountFrom,
			To:     to,
			Rate:   it.DeductPercentage.Div(hundred),
			Amount: it.DeductAmount,
		})
	}
	// Non-income formulas may encode an upper band on the formula itself.
	if f.Type != "income" && (f.UpperLimitAmount.GreaterThan(decimal.Zero) || f.UpperLimitPercentage.GreaterThan(decimal.Zero)) {
		rates.Bands = append(rates.Bands, payrollengine.Band{
			From:   f.UpperLimit,
			To:     payrollengine.Inf,
			Rate:   f.UpperLimitPercentage.Div(hundred),
			Amount: f.UpperLimitAmount,
		})
	}
	if f.Type == "income" && f.Category == "primary" {
		rates.PersonalRelief = f.PersonalRelief
	}
	rates.MinimumContribution = FormulaMinimumContribution(f)
	if split != nil {
		rates.EmployeePercentage = split.EmployeePercentage.Div(hundred)
		rates.EmployerPercentage = split.EmployerPercentage.Div(hundred)
	}
	return rates
}
