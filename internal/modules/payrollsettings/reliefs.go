package payrollsettings

import (
	"context"
	"fmt"
	"sort"
	"strings"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollrelief"
)

// Relief keys: the canonical lower-case title of each KRA relief. The settings UI sends short
// codes (personal_relief, housing_relief, ...) that map onto these.
const (
	reliefPersonal   = "personal relief"
	reliefInsurance  = "insurance relief"
	reliefHousing    = "affordable housing relief"
	reliefDisability = "disability exemption"
	reliefPension    = "pension relief"
	reliefMortgage   = "mortgage interest relief"
	// reliefPostRetirement caps the deductible post-retirement medical fund contribution.
	reliefPostRetirement = "post-retirement medical fund relief"
	// reliefNonCash is the monthly non-cash benefit threshold; while active, benefits are taxed.
	reliefNonCash = "non-cash benefit threshold"
	// reliefMeals is the monthly employer meals exemption.
	reliefMeals = "employer meals exemption"
)

// statutoryReliefs are on for every tenant by default and flagged statutory in the UI.
var statutoryReliefs = map[string]bool{reliefPersonal: true, reliefInsurance: true}

// reliefAliases maps the UI codes and short names to a relief key.
var reliefAliases = map[string]string{
	"personal":                reliefPersonal,
	"insurance":               reliefInsurance,
	"housing relief":          reliefHousing,
	"housing":                 reliefHousing,
	"ahl relief":              reliefHousing,
	"disability":              reliefDisability,
	"disability relief":       reliefDisability,
	"pension":                 reliefPension,
	"mortgage":                reliefMortgage,
	"mortgage relief":         reliefMortgage,
	"post retirement medical": reliefPostRetirement,
	"post-retirement medical": reliefPostRetirement,
	"non-cash":                reliefNonCash,
	"non cash":                reliefNonCash,
	"meals":                   reliefMeals,
}

// ReliefKey normalises a relief title or UI code (personal_relief, "Personal Relief") to its key.
func ReliefKey(s string) string {
	k := strings.Join(strings.Fields(strings.ToLower(strings.ReplaceAll(s, "_", " "))), " ")
	if a, ok := reliefAliases[k]; ok {
		return a
	}
	return k
}

// ResolvedRelief is one relief as a tenant sees it, with the values that apply.
type ResolvedRelief struct {
	ID           uuid.UUID // the row the values come from (tenant row when customised)
	Key          string
	Type         string
	Title        string
	ActualAmount bool
	FixedLimit   decimal.Decimal
	Percentage   decimal.Decimal
	PercentOf    string
	IsActive     bool
	Statutory    bool
	Source       string
	// PlatformID is the platform relief this one inherits from or overrides (nil when the tenant
	// defined a relief the platform does not have).
	PlatformID *uuid.UUID
}

func resolvedFromRow(r *ent.PayrollRelief, source string) ResolvedRelief {
	out := ResolvedRelief{
		ID: r.ID, Key: ReliefKey(r.Title), Type: r.Type, Title: r.Title, ActualAmount: r.ActualAmount,
		FixedLimit: r.FixedLimit, Percentage: r.Percentage, IsActive: r.IsActive, Source: source,
	}
	if r.PercentOf != nil {
		out.PercentOf = *r.PercentOf
	}
	out.Statutory = statutoryReliefs[out.Key]
	return out
}

// mergeReliefs is the pure overlay of a tenant's relief rows on the platform reliefs, by key. A
// tenant row with no amounts (fixed limit and percentage both zero) is an activation choice only:
// it switches the platform relief on or off and keeps the platform's values, so a later platform
// rate change still reaches the tenant.
func mergeReliefs(rows []*ent.PayrollRelief, tenantID, systemTenant uuid.UUID) []ResolvedRelief {
	platformTenant := systemTenant != uuid.Nil && tenantID == systemTenant
	plat := map[string]*ent.PayrollRelief{}
	own := map[string]*ent.PayrollRelief{}
	for _, r := range rows {
		k := ReliefKey(r.Title)
		switch {
		case platformTenant || r.TenantID == systemTenant:
			if cur, ok := plat[k]; !ok || r.UpdatedAt.After(cur.UpdatedAt) {
				plat[k] = r
			}
		case r.TenantID == tenantID:
			if cur, ok := own[k]; !ok || r.UpdatedAt.After(cur.UpdatedAt) {
				own[k] = r
			}
		}
	}
	out := make([]ResolvedRelief, 0, len(plat)+len(own))
	for k, p := range plat {
		rr := resolvedFromRow(p, SourcePlatform)
		pid := p.ID
		rr.PlatformID = &pid
		if t, ok := own[k]; ok {
			if t.FixedLimit.IsZero() && t.Percentage.IsZero() {
				rr.ID = t.ID
				rr.IsActive = t.IsActive
			} else {
				rr = resolvedFromRow(t, SourceTenant)
				rr.Title = p.Title
				rr.PlatformID = &pid
			}
			rr.Source = SourceTenant
			delete(own, k)
		}
		out = append(out, rr)
	}
	for _, t := range own {
		out = append(out, resolvedFromRow(t, SourceTenant))
	}
	sort.Slice(out, func(i, j int) bool {
		if out[i].Statutory != out[j].Statutory {
			return out[i].Statutory
		}
		return out[i].Title < out[j].Title
	})
	return out
}

// ResolveReliefs returns every relief the tenant has: platform reliefs with the tenant's choices
// applied, plus reliefs only the tenant defined. One query.
func (s *Service) ResolveReliefs(ctx context.Context, tenantID uuid.UUID) ([]ResolvedRelief, error) {
	rows, err := s.orm.PayrollRelief.Query().
		Where(payrollrelief.TenantIDIn(s.scopeTenants(tenantID)...)).All(ctx)
	if err != nil {
		return nil, err
	}
	return mergeReliefs(rows, tenantID, s.systemTenant), nil
}

// Relief returns one resolved relief by key or UI code (nil when the tenant has none).
func (s *Service) Relief(ctx context.Context, tenantID uuid.UUID, code string) (*ResolvedRelief, error) {
	all, err := s.ResolveReliefs(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	key := ReliefKey(code)
	for i := range all {
		if all[i].Key == key || strings.EqualFold(all[i].Type, code) {
			return &all[i], nil
		}
	}
	return nil, nil
}

// SetReliefActive switches a relief on or off. For a tenant it writes (or updates) a small
// activation record over the platform relief, never a copy of its amounts. For the platform
// tenant it changes the platform relief itself, which reaches every tenant without a choice of
// its own.
func (s *Service) SetReliefActive(ctx context.Context, tenantID uuid.UUID, code string, active bool) (*ResolvedRelief, error) {
	cur, err := s.Relief(ctx, tenantID, code)
	if err != nil {
		return nil, err
	}
	if cur == nil {
		return nil, ErrNotFound
	}
	if s.IsPlatformTenant(tenantID) || cur.Source == SourceTenant {
		if err := s.orm.PayrollRelief.UpdateOneID(cur.ID).SetIsActive(active).Exec(ctx); err != nil {
			return nil, err
		}
	} else {
		if _, err := s.orm.PayrollRelief.Create().
			SetTenantID(tenantID).SetType(cur.Type).SetTitle(cur.Title).
			SetActualAmount(cur.ActualAmount).SetFixedLimit(decimal.Zero).SetPercentage(decimal.Zero).
			SetIsActive(active).Save(ctx); err != nil {
			return nil, err
		}
	}
	return s.Relief(ctx, tenantID, code)
}

// RevertRelief deletes the tenant's own rows for a relief so the platform relief applies again.
func (s *Service) RevertRelief(ctx context.Context, tenantID uuid.UUID, code string) (*ResolvedRelief, error) {
	if s.IsPlatformTenant(tenantID) {
		return nil, fmt.Errorf("platform reliefs have nothing to revert to")
	}
	rows, err := s.orm.PayrollRelief.Query().Where(payrollrelief.TenantID(tenantID)).All(ctx)
	if err != nil {
		return nil, err
	}
	key := ReliefKey(code)
	var ids []uuid.UUID
	for _, r := range rows {
		if ReliefKey(r.Title) == key {
			ids = append(ids, r.ID)
		}
	}
	if len(ids) > 0 {
		if _, err := s.orm.PayrollRelief.Delete().
			Where(payrollrelief.TenantID(tenantID), payrollrelief.IDIn(ids...)).Exec(ctx); err != nil {
			return nil, err
		}
	}
	return s.Relief(ctx, tenantID, code)
}

// DedupeTenantReliefs deletes a tenant's relief rows that repeat the platform relief exactly
// (same title, type, amounts and on/off state). Such rows were copied per tenant by an earlier
// bootstrap; removing them changes nothing the tenant sees or pays, and lets later platform rate
// changes reach the tenant. Returns how many rows were removed.
func (s *Service) DedupeTenantReliefs(ctx context.Context, tenantID uuid.UUID) (int, error) {
	if s.systemTenant == uuid.Nil || s.IsPlatformTenant(tenantID) {
		return 0, nil
	}
	rows, err := s.orm.PayrollRelief.Query().
		Where(payrollrelief.TenantIDIn(tenantID, s.systemTenant)).All(ctx)
	if err != nil {
		return 0, err
	}
	plat := map[string]*ent.PayrollRelief{}
	for _, r := range rows {
		if r.TenantID == s.systemTenant {
			plat[ReliefKey(r.Title)] = r
		}
	}
	var ids []uuid.UUID
	for _, r := range rows {
		if r.TenantID != tenantID {
			continue
		}
		p, ok := plat[ReliefKey(r.Title)]
		if ok && sameRelief(r, p) {
			ids = append(ids, r.ID)
		}
	}
	if len(ids) == 0 {
		return 0, nil
	}
	return s.orm.PayrollRelief.Delete().Where(payrollrelief.TenantID(tenantID), payrollrelief.IDIn(ids...)).Exec(ctx)
}

func sameRelief(a, b *ent.PayrollRelief) bool {
	po := func(p *string) string {
		if p == nil {
			return ""
		}
		return *p
	}
	return a.Type == b.Type && a.ActualAmount == b.ActualAmount && a.IsActive == b.IsActive &&
		a.FixedLimit.Equal(b.FixedLimit) && a.Percentage.Equal(b.Percentage) && po(a.PercentOf) == po(b.PercentOf)
}
