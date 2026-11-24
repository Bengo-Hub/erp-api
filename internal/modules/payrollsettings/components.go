package payrollsettings

import (
	"context"
	"encoding/json"
	"fmt"
	"sort"
	"strings"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/generalhrsettings"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollcomponent"
)

// ComponentChoicesKey is the AppSetting key holding a tenant's choices over the platform
// component catalogue: one small record per component code (on or off, and any values the
// tenant set). The platform component rows themselves are never copied per tenant.
const ComponentChoicesKey = "payroll.components"

// ComponentChoice is a tenant's choice for one platform component.
type ComponentChoice struct {
	Active             *bool            `json:"active,omitempty"`
	Title              string           `json:"title,omitempty"`
	Amount             *decimal.Decimal `json:"amount,omitempty"`
	Percentage         *decimal.Decimal `json:"percentage,omitempty"`
	EmployerAmount     *decimal.Decimal `json:"employer_amount,omitempty"`
	EmployerPercentage *decimal.Decimal `json:"employer_percentage,omitempty"`
}

// customised reports whether the choice changes any value (beyond on or off).
func (c ComponentChoice) customised() bool {
	return c.Title != "" || c.Amount != nil || c.Percentage != nil || c.EmployerAmount != nil || c.EmployerPercentage != nil
}

// ResolvedComponent is one payroll component as a tenant sees it, with the values that apply.
type ResolvedComponent struct {
	Component *ent.PayrollComponent // the platform or tenant row
	Code      string
	Source    string
	// Active is whether the component applies for the tenant.
	Active bool
	// DefaultActive is what Active would be without the tenant's choice.
	DefaultActive bool
	Customised    bool
	ManagedBy     string
	Statutory     bool
	// StatutoryToggle is the engine code of the tenant toggle governing a statutory component.
	StatutoryToggle string

	Title              string
	Amount             decimal.Decimal
	Percentage         decimal.Decimal
	EmployerAmount     decimal.Decimal
	EmployerPercentage decimal.Decimal
}

// choiceKey is the key a platform component's choice is stored under: its code, else its id.
func choiceKey(c *ent.PayrollComponent) string {
	if c.WbCode != nil && *c.WbCode != "" {
		return *c.WbCode
	}
	return c.ID.String()
}

// resolveComponent applies the tenant's choice and statutory toggles to one row.
func resolveComponent(c *ent.PayrollComponent, tenantID, systemTenant uuid.UUID, choices map[string]ComponentChoice, toggles statutoryToggleSet) ResolvedComponent {
	r := ResolvedComponent{
		Component: c, Title: c.Title, Statutory: c.Statutory,
		Amount: c.Amount, Percentage: c.Percentage, EmployerAmount: c.EmployerAmount, EmployerPercentage: c.EmployerPercentage,
	}
	if c.WbCode != nil {
		r.Code = *c.WbCode
	}
	isPlatformRow := systemTenant != uuid.Nil && c.TenantID == systemTenant
	if !isPlatformRow || tenantID == systemTenant {
		r.Source = SourceTenant
		if isPlatformRow {
			r.Source = SourcePlatform
		}
		if it, ok := catalogueByCode[r.Code]; ok && isPlatformRow {
			r.ManagedBy = it.ManagedBy
		}
		r.Active, r.DefaultActive = c.IsActive, c.IsActive
		return r
	}
	r.Source = SourcePlatform
	if it, ok := catalogueByCode[r.Code]; ok {
		r.ManagedBy = it.ManagedBy
	}
	// Default: statutory and module-managed components are on, the rest are opt-in. A platform
	// row switched off by the platform owner is off for everyone.
	r.DefaultActive = c.IsActive && (c.Statutory || r.ManagedBy != "")
	r.Active = r.DefaultActive
	if comp, ok := statutoryToggleOf[r.Code]; ok && c.Statutory {
		r.StatutoryToggle = comp
		r.Active = c.IsActive && toggles.enabled(comp)
		return r
	}
	ch, ok := choices[choiceKey(c)]
	if !ok {
		return r
	}
	if ch.Active != nil {
		r.Active = c.IsActive && *ch.Active
	}
	if ch.customised() {
		r.Customised = true
		r.Source = SourceTenant
		if ch.Title != "" {
			r.Title = ch.Title
		}
		if ch.Amount != nil {
			r.Amount = *ch.Amount
		}
		if ch.Percentage != nil {
			r.Percentage = *ch.Percentage
		}
		if ch.EmployerAmount != nil {
			r.EmployerAmount = *ch.EmployerAmount
		}
		if ch.EmployerPercentage != nil {
			r.EmployerPercentage = *ch.EmployerPercentage
		}
	}
	return r
}

// mergeComponents is the pure list merge: the tenant's own components plus the platform
// catalogue, where a tenant component with the same code or title replaces the platform one.
// Statutory components come first, then by title.
func mergeComponents(rows []*ent.PayrollComponent, tenantID, systemTenant uuid.UUID, choices map[string]ComponentChoice, toggles statutoryToggleSet) []ResolvedComponent {
	platformTenant := systemTenant != uuid.Nil && tenantID == systemTenant
	ownCodes, ownTitles := map[string]bool{}, map[string]bool{}
	if !platformTenant {
		for _, c := range rows {
			if c.TenantID != tenantID {
				continue
			}
			if c.WbCode != nil && *c.WbCode != "" {
				ownCodes[*c.WbCode] = true
			}
			ownTitles[strings.ToLower(strings.TrimSpace(c.Title))] = true
		}
	}
	out := make([]ResolvedComponent, 0, len(rows))
	for _, c := range rows {
		if !platformTenant && c.TenantID == systemTenant {
			if (c.WbCode != nil && ownCodes[*c.WbCode]) || ownTitles[strings.ToLower(strings.TrimSpace(c.Title))] {
				continue
			}
		}
		out = append(out, resolveComponent(c, tenantID, systemTenant, choices, toggles))
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Statutory != out[j].Statutory {
			return out[i].Statutory
		}
		return strings.ToLower(out[i].Title) < strings.ToLower(out[j].Title)
	})
	return out
}

// componentChoices loads the tenant's catalogue choices (empty when none saved).
func (s *Service) componentChoices(ctx context.Context, tenantID uuid.UUID) (map[string]ComponentChoice, error) {
	out := map[string]ComponentChoice{}
	row, err := s.orm.AppSetting.Query().
		Where(appsetting.TenantID(tenantID), appsetting.AppKey(ComponentChoicesKey)).Only(ctx)
	if ent.IsNotFound(err) {
		return out, nil
	}
	if err != nil {
		return nil, err
	}
	if row.Value != "" {
		if err := json.Unmarshal([]byte(row.Value), &out); err != nil {
			return nil, fmt.Errorf("decode component choices: %w", err)
		}
	}
	return out, nil
}

func (s *Service) saveComponentChoices(ctx context.Context, tenantID uuid.UUID, choices map[string]ComponentChoice) error {
	raw, err := json.Marshal(choices)
	if err != nil {
		return err
	}
	return s.orm.AppSetting.Create().
		SetTenantID(tenantID).SetAppKey(ComponentChoicesKey).SetValue(string(raw)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).
		UpdateNewValues().Exec(ctx)
}

// componentContext loads what component resolution needs besides the rows: the tenant's choices
// and statutory toggles (two queries).
func (s *Service) componentContext(ctx context.Context, tenantID uuid.UUID) (map[string]ComponentChoice, statutoryToggleSet, error) {
	choices, err := s.componentChoices(ctx, tenantID)
	if err != nil {
		return nil, allStatutoryOn, err
	}
	toggles, err := s.statutoryToggles(ctx, tenantID)
	if err != nil {
		return nil, allStatutoryOn, err
	}
	return choices, toggles, nil
}

// ResolveComponents lists the components a tenant sees (optionally one category): its own plus
// the platform catalogue with its choices applied. Three queries whatever the catalogue size.
func (s *Service) ResolveComponents(ctx context.Context, tenantID uuid.UUID, category string) ([]ResolvedComponent, error) {
	q := s.orm.PayrollComponent.Query().Where(payrollcomponent.TenantIDIn(s.scopeTenants(tenantID)...))
	if category != "" {
		q = q.Where(payrollcomponent.Category(category))
	}
	rows, err := q.Order(ent.Asc(payrollcomponent.FieldTitle)).All(ctx)
	if err != nil {
		return nil, err
	}
	choices, toggles, err := s.componentContext(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	return mergeComponents(rows, tenantID, s.systemTenant, choices, toggles), nil
}

// ComponentsByID resolves the given component ids (the tenant's or platform ones) in one query,
// for payroll runs and payslips. Ids outside the tenant's scope are left out.
func (s *Service) ComponentsByID(ctx context.Context, tenantID uuid.UUID, ids []uuid.UUID) (map[uuid.UUID]ResolvedComponent, error) {
	out := map[uuid.UUID]ResolvedComponent{}
	if len(ids) == 0 {
		return out, nil
	}
	rows, err := s.orm.PayrollComponent.Query().
		Where(payrollcomponent.IDIn(ids...), payrollcomponent.TenantIDIn(s.scopeTenants(tenantID)...)).All(ctx)
	if err != nil {
		return nil, err
	}
	choices, toggles, err := s.componentContext(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	for _, c := range rows {
		out[c.ID] = resolveComponent(c, tenantID, s.systemTenant, choices, toggles)
	}
	return out, nil
}

// Component resolves one component the tenant can see.
func (s *Service) Component(ctx context.Context, tenantID, id uuid.UUID) (*ResolvedComponent, error) {
	m, err := s.ComponentsByID(ctx, tenantID, []uuid.UUID{id})
	if err != nil {
		return nil, err
	}
	r, ok := m[id]
	if !ok {
		return nil, ErrNotFound
	}
	return &r, nil
}

// SetComponentActive switches a component on or off for the tenant. The tenant's own component is
// updated in place; a statutory platform component flips the tenant's statutory toggle (the same
// switch as the Tax and Statutory tab, so there is one source of truth); any other platform
// component records the choice in the tenant's catalogue choices.
func (s *Service) SetComponentActive(ctx context.Context, tenantID, id uuid.UUID, active bool) (*ResolvedComponent, error) {
	cur, err := s.Component(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	c := cur.Component
	switch {
	case c.TenantID == tenantID:
		if err := s.orm.PayrollComponent.UpdateOneID(id).SetIsActive(active).Exec(ctx); err != nil {
			return nil, err
		}
	case cur.StatutoryToggle != "":
		if err := s.setStatutoryToggle(ctx, tenantID, cur.StatutoryToggle, active); err != nil {
			return nil, err
		}
	default:
		choices, err := s.componentChoices(ctx, tenantID)
		if err != nil {
			return nil, err
		}
		k := choiceKey(c)
		ch := choices[k]
		if active == cur.DefaultActive && !ch.customised() {
			delete(choices, k)
		} else {
			ch.Active = &active
			choices[k] = ch
		}
		if err := s.saveComponentChoices(ctx, tenantID, choices); err != nil {
			return nil, err
		}
	}
	return s.Component(ctx, tenantID, id)
}

// CustomiseComponent records the tenant's own values for a platform component (title, amounts,
// rates, and optionally on or off). Only the fields set in ch change.
func (s *Service) CustomiseComponent(ctx context.Context, tenantID, id uuid.UUID, ch ComponentChoice) (*ResolvedComponent, error) {
	cur, err := s.Component(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if cur.Component.TenantID == tenantID {
		return nil, fmt.Errorf("this component belongs to your organisation: edit it directly")
	}
	for _, v := range []*decimal.Decimal{ch.Amount, ch.Percentage, ch.EmployerAmount, ch.EmployerPercentage} {
		if v != nil && v.IsNegative() {
			return nil, fmt.Errorf("amounts and percentages cannot be negative")
		}
	}
	// Keep only the values that differ from the platform row, so saving the form unchanged
	// leaves the tenant on the platform values (and later platform changes still reach it).
	base := cur.Component
	for _, p := range []struct {
		v    **decimal.Decimal
		base decimal.Decimal
	}{{&ch.Amount, base.Amount}, {&ch.Percentage, base.Percentage}, {&ch.EmployerAmount, base.EmployerAmount}, {&ch.EmployerPercentage, base.EmployerPercentage}} {
		if *p.v != nil && (*p.v).Equal(p.base) {
			*p.v = nil
		}
	}
	if ch.Active != nil && cur.StatutoryToggle != "" {
		if err := s.setStatutoryToggle(ctx, tenantID, cur.StatutoryToggle, *ch.Active); err != nil {
			return nil, err
		}
		ch.Active = nil
	}
	choices, err := s.componentChoices(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	k := choiceKey(cur.Component)
	prev := choices[k]
	if ch.Active == nil {
		ch.Active = prev.Active
	}
	if ch.Title == "" {
		ch.Title = prev.Title
	}
	if ch.Title == cur.Component.Title {
		ch.Title = ""
	}
	if !ch.customised() && (ch.Active == nil || *ch.Active == cur.DefaultActive) {
		delete(choices, k)
	} else {
		choices[k] = ch
	}
	if err := s.saveComponentChoices(ctx, tenantID, choices); err != nil {
		return nil, err
	}
	return s.Component(ctx, tenantID, id)
}

// RevertComponent drops the tenant's choice for a platform component, so the platform default
// (values and on or off) applies again. A statutory toggle is switched back on.
func (s *Service) RevertComponent(ctx context.Context, tenantID, id uuid.UUID) (*ResolvedComponent, error) {
	cur, err := s.Component(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if cur.Component.TenantID == tenantID {
		return nil, fmt.Errorf("this component belongs to your organisation: there is no platform default to revert to")
	}
	if cur.StatutoryToggle != "" && !cur.Active {
		if err := s.setStatutoryToggle(ctx, tenantID, cur.StatutoryToggle, true); err != nil {
			return nil, err
		}
	}
	choices, err := s.componentChoices(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	if _, ok := choices[choiceKey(cur.Component)]; ok {
		delete(choices, choiceKey(cur.Component))
		if err := s.saveComponentChoices(ctx, tenantID, choices); err != nil {
			return nil, err
		}
	}
	return s.Component(ctx, tenantID, id)
}

// setStatutoryToggle writes one statutory toggle on the tenant's general HR settings row,
// creating the row (all other toggles on) when the tenant has none.
func (s *Service) setStatutoryToggle(ctx context.Context, tenantID uuid.UUID, comp string, on bool) error {
	g, err := s.orm.GeneralHRSettings.Query().Where(generalhrsettings.TenantID(tenantID)).Only(ctx)
	if ent.IsNotFound(err) {
		g, err = s.orm.GeneralHRSettings.Create().SetTenantID(tenantID).Save(ctx)
	}
	if err != nil {
		return err
	}
	u := g.Update()
	switch comp {
	case "paye":
		u = u.SetPayeEnabled(on)
	case "nssf":
		u = u.SetNssfEnabled(on)
	case "shif", "nhif":
		u = u.SetShifEnabled(on)
	case "housing_levy":
		u = u.SetHousingLevyEnabled(on)
	case "nita":
		u = u.SetNitaEnabled(on)
	default:
		return fmt.Errorf("unknown statutory component %q", comp)
	}
	return u.Exec(ctx)
}
