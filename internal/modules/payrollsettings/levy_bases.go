package payrollsettings

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
)

// Levy bases say, per earning, which levies it counts for: PAYE, NSSF, SHIF, Housing Levy, and
// whether it is pensionable (the 30% pension deduction limit, Income Tax Act s.22A). They are
// data: versioned by the month they start, set on the platform and overridable per tenant, kept
// in app settings under LevyBasesKey as {earning code: [rules]}. An earning without a rule
// follows its tax treatment: a taxable earning counts for every levy, a tax-free one for none,
// and only basic pay is pensionable. Those defaults are what payroll did before the flags.
const LevyBasesKey = "payroll.levy_bases"

// LevyFlags is one earning's treatment.
type LevyFlags struct {
	PAYE        bool `json:"paye"`
	NSSF        bool `json:"nssf"`
	SHIF        bool `json:"shif"`
	HousingLevy bool `json:"housing_levy"`
	Pensionable bool `json:"pensionable"`
}

// LevyRule is a treatment in force from a month (YYYY-MM).
type LevyRule struct {
	From  string    `json:"from"`
	Flags LevyFlags `json:"flags"`
}

// LevyBases maps earning codes to their rules.
type LevyBases map[string][]LevyRule

// DefaultLevyFlags is the treatment of an earning without a rule.
func DefaultLevyFlags(code, taxableStatus string) LevyFlags {
	in := taxableStatus != "nontaxable"
	return LevyFlags{PAYE: in, NSSF: in, SHIF: in, HousingLevy: in, Pensionable: code == "basic"}
}

// ruleFor picks the rule in force for the period month, if any.
func ruleFor(rules []LevyRule, period time.Time) (LevyFlags, bool) {
	month := period.Format("2006-01")
	var best *LevyRule
	for i := range rules {
		r := &rules[i]
		if r.From <= month && (best == nil || r.From > best.From) {
			best = r
		}
	}
	if best == nil {
		return LevyFlags{}, false
	}
	return best.Flags, true
}

// LevyResolver answers an earning's treatment for one period (tenant rules over platform rules
// over the default).
type LevyResolver struct {
	period           time.Time
	tenant, platform LevyBases
}

// NewLevyResolver builds a resolver from rules already loaded (tests, previews).
func NewLevyResolver(period time.Time, tenant, platform LevyBases) *LevyResolver {
	return &LevyResolver{period: period, tenant: tenant, platform: platform}
}

// Flags returns the treatment of an earning code for the resolver's period.
func (r *LevyResolver) Flags(code, taxableStatus string) LevyFlags {
	if r != nil {
		if f, ok := ruleFor(r.tenant[code], r.period); ok {
			return f
		}
		if f, ok := ruleFor(r.platform[code], r.period); ok {
			return f
		}
	}
	return DefaultLevyFlags(code, taxableStatus)
}

func (s *Service) readLevyBases(ctx context.Context, tenantID uuid.UUID) (LevyBases, error) {
	out := LevyBases{}
	if tenantID == uuid.Nil {
		return out, nil
	}
	row, err := s.orm.AppSetting.Query().Where(appsetting.TenantID(tenantID), appsetting.AppKey(LevyBasesKey)).Only(ctx)
	if ent.IsNotFound(err) {
		return out, nil
	}
	if err != nil {
		return nil, err
	}
	if err := json.Unmarshal([]byte(row.Value), &out); err != nil {
		return nil, fmt.Errorf("payroll levy bases: %w", err)
	}
	return out, nil
}

// LevyResolver loads the tenant's and the platform's levy bases for a run's period.
func (s *Service) LevyResolver(ctx context.Context, tenantID uuid.UUID, period time.Time) (*LevyResolver, error) {
	r := &LevyResolver{period: period}
	var err error
	if r.platform, err = s.readLevyBases(ctx, s.systemTenant); err != nil {
		return nil, err
	}
	if tenantID != s.systemTenant {
		if r.tenant, err = s.readLevyBases(ctx, tenantID); err != nil {
			return nil, err
		}
	}
	return r, nil
}

// LevyBases returns the tenant's own levy bases (the platform's for the platform tenant).
func (s *Service) LevyBases(ctx context.Context, tenantID uuid.UUID) (LevyBases, error) {
	return s.readLevyBases(ctx, tenantID)
}

// CancelLevyRule removes the tenant's rule for an earning that starts in a later month (set by
// mistake). A rule already in force is history and stays.
func (s *Service) CancelLevyRule(ctx context.Context, tenantID uuid.UUID, code, from string) (LevyBases, error) {
	if from <= time.Now().UTC().Format("2006-01") {
		return nil, fmt.Errorf("only a rule starting in a later month can be cancelled")
	}
	bases, err := s.readLevyBases(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rules := bases[code]
	kept := rules[:0:0]
	for _, r := range rules {
		if r.From != from {
			kept = append(kept, r)
		}
	}
	if len(kept) == len(rules) {
		return nil, fmt.Errorf("no %s rule starts in %s", code, from)
	}
	if len(kept) == 0 {
		delete(bases, code)
	} else {
		bases[code] = kept
	}
	return bases, s.writeLevyBases(ctx, tenantID, bases)
}

func (s *Service) writeLevyBases(ctx context.Context, tenantID uuid.UUID, bases LevyBases) error {
	raw, err := json.Marshal(bases)
	if err != nil {
		return err
	}
	return s.orm.AppSetting.Create().SetTenantID(tenantID).SetAppKey(LevyBasesKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).UpdateNewValues().Exec(ctx)
}

// SetLevyRule adds or replaces the rule for an earning code from a month. Earlier months keep
// their rules, so past payroll is unchanged.
func (s *Service) SetLevyRule(ctx context.Context, tenantID uuid.UUID, code string, rule LevyRule) (LevyBases, error) {
	code = strings.TrimSpace(code)
	if code == "" {
		return nil, fmt.Errorf("earning code is required")
	}
	if _, err := time.Parse("2006-01", rule.From); err != nil {
		return nil, fmt.Errorf("from must be a month like 2026-12")
	}
	if rule.From < time.Now().UTC().Format("2006-01") {
		return nil, fmt.Errorf("a levy rule starts this month or later: months already paid keep their rules")
	}
	bases, err := s.readLevyBases(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	rules := bases[code]
	replaced := false
	for i := range rules {
		if rules[i].From == rule.From {
			rules[i] = rule
			replaced = true
		}
	}
	if !replaced {
		rules = append(rules, rule)
	}
	sort.Slice(rules, func(i, j int) bool { return rules[i].From < rules[j].From })
	bases[code] = rules
	raw, err := json.Marshal(bases)
	if err != nil {
		return nil, err
	}
	if err := s.orm.AppSetting.Create().SetTenantID(tenantID).SetAppKey(LevyBasesKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).UpdateNewValues().Exec(ctx); err != nil {
		return nil, err
	}
	return bases, nil
}
