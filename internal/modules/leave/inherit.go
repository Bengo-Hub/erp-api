package leave

import (
	"context"
	"errors"
	"fmt"
	"sort"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
	"github.com/Bengo-Hub/erp-api/internal/modules/inherited"
)

// Inherit and customise model for leave types.
//
// The platform's leave types are rows of the system tenant, which every company inherits. A
// company customises one with a small override record (TypeOverridesKey, keyed by the platform
// type's id, holding only the changed fields), so balances, requests and entitlements keep the
// platform id. Revert removes the record. A company's own type with the same name (case and
// spaces ignored) takes the place of the platform one; any other own type is simply its own.

// TypeOverridesKey is the AppSetting key holding a company's changes to inherited leave types.
const TypeOverridesKey = "leave.types"

var (
	// ErrNotCustomised is returned when reverting a leave type that has no changes.
	ErrNotCustomised = errors.New("this leave type has no changes to revert")
	// ErrInheritedName refuses renaming a platform leave type.
	ErrInheritedName = errors.New("a platform leave type keeps its name; add your own leave type to use another name")
)

// UsableCategory is a leave type the company uses (its own, or an inherited one with its changes).
func (s *Service) UsableCategory(ctx context.Context, tenantID, id uuid.UUID) (*ent.LeaveCategory, error) {
	return s.usableCategory(ctx, tenantID, id)
}

// TypeOverride is a company's change to an inherited leave type; a nil field keeps the platform
// value.
type TypeOverride struct {
	Description       *string          `json:"description,omitempty"`
	IsActive          *bool            `json:"is_active,omitempty"`
	IsPaid            *bool            `json:"is_paid,omitempty"`
	DefaultAnnualDays *decimal.Decimal `json:"default_annual_days,omitempty"`
	AllowCarryover    *bool            `json:"allow_carryover,omitempty"`
	MaxCarryoverDays  *decimal.Decimal `json:"max_carryover_days,omitempty"`
}

func (o TypeOverride) empty() bool {
	return o.Description == nil && o.IsActive == nil && o.IsPaid == nil && o.DefaultAnnualDays == nil &&
		o.AllowCarryover == nil && o.MaxCarryoverDays == nil
}

// apply returns a copy of the platform row with the company's changes.
func (o TypeOverride) apply(c *ent.LeaveCategory) *ent.LeaveCategory {
	out := *c
	if o.Description != nil {
		out.Description = *o.Description
	}
	if o.IsActive != nil {
		out.IsActive = *o.IsActive
	}
	if o.IsPaid != nil {
		out.IsPaid = *o.IsPaid
	}
	if o.DefaultAnnualDays != nil {
		out.DefaultAnnualDays = *o.DefaultAnnualDays
	}
	if o.AllowCarryover != nil {
		out.AllowCarryover = *o.AllowCarryover
	}
	if o.MaxCarryoverDays != nil {
		out.MaxCarryoverDays = *o.MaxCarryoverDays
	}
	return &out
}

// diff keeps only the values that differ from the platform row.
func diff(platform *ent.LeaveCategory, in CategoryInput) TypeOverride {
	var o TypeOverride
	if in.Description != platform.Description {
		o.Description = &in.Description
	}
	if in.IsActive != platform.IsActive {
		o.IsActive = &in.IsActive
	}
	if in.IsPaid != platform.IsPaid {
		o.IsPaid = &in.IsPaid
	}
	if !in.DefaultAnnualDays.Equal(platform.DefaultAnnualDays) {
		o.DefaultAnnualDays = &in.DefaultAnnualDays
	}
	if in.AllowCarryover != platform.AllowCarryover {
		o.AllowCarryover = &in.AllowCarryover
	}
	if !in.MaxCarryoverDays.Equal(platform.MaxCarryoverDays) {
		o.MaxCarryoverDays = &in.MaxCarryoverDays
	}
	return o
}

// NameKey is how a company's own type is matched to a platform type: case and spaces ignored.
func NameKey(name string) string { return inherited.NameKey(name) }

func typeOverrides(ctx context.Context, c *ent.Client, tenantID uuid.UUID) (map[string]TypeOverride, error) {
	m, err := inherited.Load[TypeOverride](ctx, c, tenantID, TypeOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("leave: %w", err)
	}
	return m, nil
}

func saveTypeOverrides(ctx context.Context, c *ent.Client, tenantID uuid.UUID, m map[string]TypeOverride) error {
	if err := inherited.Save(ctx, c, tenantID, TypeOverridesKey, m); err != nil {
		return fmt.Errorf("leave: %w", err)
	}
	return nil
}

// resolvedCategories is every leave type a company uses, by name: its own, and the platform's
// (with its changes) that no own type of the same name replaces. customised lists the inherited
// types it changed.
func (s *Service) resolvedCategories(ctx context.Context, tenantID uuid.UUID) (rows []*ent.LeaveCategory, customised map[uuid.UUID]bool, err error) {
	tenants := []uuid.UUID{tenantID}
	inherits := s.systemTenant != uuid.Nil && s.systemTenant != tenantID
	if inherits {
		tenants = append(tenants, s.systemTenant)
	}
	all, err := s.orm.LeaveCategory.Query().Where(leavecategory.TenantIDIn(tenants...)).All(ctx)
	if err != nil {
		return nil, nil, err
	}
	customised = map[uuid.UUID]bool{}
	own := map[string]bool{}
	for _, c := range all {
		if c.TenantID == tenantID {
			own[NameKey(c.Name)] = true
		}
	}
	var changes map[string]TypeOverride
	if inherits {
		if changes, err = typeOverrides(ctx, s.orm, tenantID); err != nil {
			return nil, nil, err
		}
	}
	for _, c := range all {
		if c.TenantID != tenantID {
			if own[NameKey(c.Name)] {
				continue
			}
			if o, ok := changes[c.ID.String()]; ok && !o.empty() {
				c = o.apply(c)
				customised[c.ID] = true
			}
		}
		rows = append(rows, c)
	}
	sort.SliceStable(rows, func(i, j int) bool { return rows[i].Name < rows[j].Name })
	return rows, customised, nil
}

// withChanges returns an inherited type as the company sees it (its changes applied); an own
// type is returned as is.
func (s *Service) withChanges(ctx context.Context, c *ent.Client, tenantID uuid.UUID, cat *ent.LeaveCategory) (*ent.LeaveCategory, error) {
	if cat.TenantID == tenantID {
		return cat, nil
	}
	m, err := typeOverrides(ctx, c, tenantID)
	if err != nil {
		return nil, err
	}
	if o, ok := m[cat.ID.String()]; ok {
		return o.apply(cat), nil
	}
	return cat, nil
}

// inheritedCategory is a platform type the company uses (not replaced by an own type).
func (s *Service) inheritedCategory(ctx context.Context, tenantID, id uuid.UUID) (*ent.LeaveCategory, error) {
	if s.systemTenant == uuid.Nil || s.systemTenant == tenantID {
		return nil, ErrUnknownCategory
	}
	c, err := s.orm.LeaveCategory.Query().Where(leavecategory.ID(id), leavecategory.TenantID(s.systemTenant)).Only(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrUnknownCategory
	}
	if err != nil {
		return nil, fmt.Errorf("leave: load leave type: %w", err)
	}
	replaced, err := s.orm.LeaveCategory.Query().Where(leavecategory.TenantID(tenantID)).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("leave: load leave types: %w", err)
	}
	for _, r := range replaced {
		if NameKey(r.Name) == NameKey(c.Name) {
			return nil, ErrUnknownCategory
		}
	}
	return c, nil
}

// CustomiseCategory saves a company's changes to an inherited leave type: only the values that
// differ from the platform type are kept, so the type follows later platform changes to the rest.
// Its name stays the platform's.
func (s *Service) CustomiseCategory(ctx context.Context, tenantID, id uuid.UUID, in CategoryInput) (*ent.LeaveCategory, error) {
	platform, err := s.inheritedCategory(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	m, err := typeOverrides(ctx, s.orm, tenantID)
	if err != nil {
		return nil, err
	}
	o := diff(platform, in)
	if o.empty() {
		delete(m, id.String())
	} else {
		m[id.String()] = o
	}
	if err := saveTypeOverrides(ctx, s.orm, tenantID, m); err != nil {
		return nil, err
	}
	return o.apply(platform), nil
}

// RevertCategory drops a company's changes to an inherited leave type.
func (s *Service) RevertCategory(ctx context.Context, tenantID, id uuid.UUID) (*ent.LeaveCategory, error) {
	platform, err := s.inheritedCategory(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	m, err := typeOverrides(ctx, s.orm, tenantID)
	if err != nil {
		return nil, err
	}
	if _, ok := m[id.String()]; !ok {
		return nil, ErrNotCustomised
	}
	delete(m, id.String())
	if err := saveTypeOverrides(ctx, s.orm, tenantID, m); err != nil {
		return nil, err
	}
	return platform, nil
}
