package payrollsettings

import (
	"context"
	"errors"
	"fmt"
	"sort"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformulaitem"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollsplitratio"
)

// Inherit and override model.
//
// Payroll configuration (formulas, reliefs and components) lives ONCE at platform level, as rows
// owned by the synthetic system tenant (PAYROLL_SYSTEM_TENANT_ID). Every tenant inherits those
// rows. A tenant customises a single formula or relief by holding its own row for the same key,
// and a platform component through a small override record (see components.go). Every reader
// (settings lists, the payroll engine config, payslip lines and reports) resolves through this
// file and components.go: the tenant's own row first, then the platform row. Nothing is copied
// per tenant except the one item a tenant chooses to customise.

// Source of a resolved row.
const (
	SourcePlatform = "platform"
	SourceTenant   = "tenant"
)

var (
	// ErrPlatformReadOnly is returned when a tenant tries to change a platform default directly.
	ErrPlatformReadOnly = errors.New("this is a platform default: customise it to create your organisation's own copy")
	// ErrAlreadyCustomised is returned when a tenant already holds its own formula for the key.
	ErrAlreadyCustomised = errors.New("your organisation already has its own version of this formula")
	// ErrNotFound is returned when the row is not visible to the tenant.
	ErrNotFound = errors.New("not found")
)

// SystemTenant is the platform tenant whose rows every tenant inherits (uuid.Nil when unset).
func (s *Service) SystemTenant() uuid.UUID { return s.systemTenant }

// IsPlatformTenant reports whether id is the platform (system) tenant.
func (s *Service) IsPlatformTenant(id uuid.UUID) bool {
	return s.systemTenant != uuid.Nil && id == s.systemTenant
}

// scopeTenants is the tenant plus the platform tenant: the rows a tenant can read.
func (s *Service) scopeTenants(tenantID uuid.UUID) []uuid.UUID {
	if s.systemTenant == uuid.Nil || s.systemTenant == tenantID {
		return []uuid.UUID{tenantID}
	}
	return []uuid.UUID{tenantID, s.systemTenant}
}

// formulaKey identifies a statutory rate set: (type, category), for example (income, primary).
type formulaKey struct{ ftype, category string }

func keyOf(f *ent.PayrollFormula) formulaKey { return formulaKey{f.Type, f.Category} }

// ResolvedFormula is one formula row as a tenant sees it.
type ResolvedFormula struct {
	Formula *ent.PayrollFormula
	// Source is SourcePlatform (inherited, read-only for the tenant) or SourceTenant.
	Source string
	// OverridesID is, on a tenant row, the platform formula of the same key it replaces.
	OverridesID *uuid.UUID
}

// ListFormulas returns the formulas a tenant sees, newest effective first: the tenant's own rows
// plus every platform row whose (type, category) the tenant has not customised. One query.
func (s *Service) ListFormulas(ctx context.Context, tenantID uuid.UUID) ([]ResolvedFormula, error) {
	rows, err := s.orm.PayrollFormula.Query().
		Where(payrollformula.TenantIDIn(s.scopeTenants(tenantID)...)).
		Order(ent.Desc(payrollformula.FieldEffectiveFrom), ent.Asc(payrollformula.FieldTitle)).
		All(ctx)
	if err != nil {
		return nil, err
	}
	return mergeFormulas(rows, tenantID, s.systemTenant), nil
}

// mergeFormulas is the pure list merge behind ListFormulas. Input order is kept.
func mergeFormulas(rows []*ent.PayrollFormula, tenantID, systemTenant uuid.UUID) []ResolvedFormula {
	platform := tenantID == systemTenant && systemTenant != uuid.Nil
	owned := map[formulaKey]bool{}
	platformCurrent := map[formulaKey]uuid.UUID{}
	for _, f := range rows {
		if f.TenantID == tenantID && !platform {
			owned[keyOf(f)] = true
		}
		if f.TenantID == systemTenant && f.IsCurrent {
			platformCurrent[keyOf(f)] = f.ID
		}
	}
	out := make([]ResolvedFormula, 0, len(rows))
	for _, f := range rows {
		switch {
		case platform || f.TenantID == systemTenant:
			if !platform && owned[keyOf(f)] {
				continue // the tenant's own version replaces the platform row
			}
			out = append(out, ResolvedFormula{Formula: f, Source: SourcePlatform})
		case f.TenantID == tenantID:
			rf := ResolvedFormula{Formula: f, Source: SourceTenant}
			if id, ok := platformCurrent[keyOf(f)]; ok {
				id := id
				rf.OverridesID = &id
			}
			out = append(out, rf)
		}
	}
	return out
}

// covers reports whether a formula row applies to the period. A current row covers from its
// effective_from (open ended unless effective_to is set). A superseded (non-current) row covers
// only its bounded window, so a retired version keeps applying to the months it was in force
// (re-running an earlier month) but never to later ones.
func covers(f *ent.PayrollFormula, period time.Time) bool {
	if f.EffectiveFrom == nil || period.Before(*f.EffectiveFrom) {
		return false
	}
	if f.EffectiveTo != nil {
		return !period.After(*f.EffectiveTo)
	}
	return f.IsCurrent
}

// pickCovering returns the row of one tenant and key that applies to the period: the current
// row when it covers the period, else the most recent bounded version that does.
func pickCovering(rows []*ent.PayrollFormula, period time.Time) *ent.PayrollFormula {
	var best *ent.PayrollFormula
	for _, f := range rows {
		if !covers(f, period) {
			continue
		}
		if best == nil ||
			(f.IsCurrent && !best.IsCurrent) ||
			(f.IsCurrent == best.IsCurrent && f.EffectiveFrom.After(*best.EffectiveFrom)) {
			best = f
		}
	}
	return best
}

// pickCurrent returns the current row, preferring one without a start date (always in force).
func pickCurrent(rows []*ent.PayrollFormula) *ent.PayrollFormula {
	var cur *ent.PayrollFormula
	for _, f := range rows {
		if !f.IsCurrent {
			continue
		}
		if f.EffectiveFrom == nil {
			return f
		}
		if cur == nil {
			cur = f
		}
	}
	return cur
}

// resolveEffective picks the formula that applies to the period across the tenant's own rows and
// the platform rows of one key. Order: the tenant's row in force for the period, the platform
// row in force for the period, then the tenant's current row, then the platform's current row
// (a current row whose start date is after the period, as the last resort before failing).
func resolveEffective(tenantRows, platformRows []*ent.PayrollFormula, period time.Time) *ent.PayrollFormula {
	if f := pickCovering(tenantRows, period); f != nil {
		return f
	}
	if f := pickCovering(platformRows, period); f != nil {
		return f
	}
	if f := pickCurrent(tenantRows); f != nil {
		return f
	}
	return pickCurrent(platformRows)
}

// formulaSet is every formula row a tenant can read, split by owner and key. Loaded once per
// payroll run so the engine config resolves all statutory items from one query.
type formulaSet struct {
	tenant, platform map[formulaKey][]*ent.PayrollFormula
}

func (s *Service) loadFormulaSet(ctx context.Context, tenantID uuid.UUID, where ...func(*ent.PayrollFormulaQuery)) (*formulaSet, error) {
	q := s.orm.PayrollFormula.Query().Where(payrollformula.TenantIDIn(s.scopeTenants(tenantID)...))
	for _, w := range where {
		w(q)
	}
	rows, err := q.Order(ent.Desc(payrollformula.FieldEffectiveFrom)).All(ctx)
	if err != nil {
		return nil, err
	}
	set := &formulaSet{tenant: map[formulaKey][]*ent.PayrollFormula{}, platform: map[formulaKey][]*ent.PayrollFormula{}}
	for _, f := range rows {
		if f.TenantID == tenantID {
			set.tenant[keyOf(f)] = append(set.tenant[keyOf(f)], f)
		} else {
			set.platform[keyOf(f)] = append(set.platform[keyOf(f)], f)
		}
	}
	return set, nil
}

// effective resolves one key from the preloaded set. An empty category matches any category of
// the type (legacy callers).
func (fs *formulaSet) effective(ftype, category string, period time.Time) *ent.PayrollFormula {
	if category != "" {
		k := formulaKey{ftype, category}
		return resolveEffective(fs.tenant[k], fs.platform[k], period)
	}
	var t, p []*ent.PayrollFormula
	for k, rows := range fs.tenant {
		if k.ftype == ftype {
			t = append(t, rows...)
		}
	}
	for k, rows := range fs.platform {
		if k.ftype == ftype {
			p = append(p, rows...)
		}
	}
	return resolveEffective(t, p, period)
}

// EffectiveFormula resolves the single formula for (type, category) in force at the period,
// preferring the tenant's own rows then the platform defaults. Returns a typed error if none is
// configured (fail loud).
func (s *Service) EffectiveFormula(ctx context.Context, tenantID uuid.UUID, ftype, category string, period time.Time) (*ent.PayrollFormula, error) {
	set, err := s.loadFormulaSet(ctx, tenantID, func(q *ent.PayrollFormulaQuery) {
		q.Where(payrollformula.TypeEQ(ftype))
		if category != "" {
			q.Where(payrollformula.CategoryEQ(category))
		}
	})
	if err != nil {
		return nil, err
	}
	if f := set.effective(ftype, category, period); f != nil {
		return f, nil
	}
	return nil, fmt.Errorf("payrollsettings: no current %s/%s formula effective at %s", ftype, category, period.Format("2006-01-02"))
}

// visibleFormula loads a formula the tenant can read (its own or a platform row).
func (s *Service) visibleFormula(ctx context.Context, tenantID, formulaID uuid.UUID) (*ent.PayrollFormula, error) {
	f, err := s.orm.PayrollFormula.Query().
		Where(payrollformula.ID(formulaID), payrollformula.TenantIDIn(s.scopeTenants(tenantID)...)).
		Only(ctx)
	if ent.IsNotFound(err) {
		return nil, ErrNotFound
	}
	return f, err
}

// FormulaSource reports how a tenant sees a formula row.
func (s *Service) FormulaSource(tenantID uuid.UUID, f *ent.PayrollFormula) string {
	if f.TenantID == tenantID && !s.IsPlatformTenant(tenantID) {
		return SourceTenant
	}
	return SourcePlatform
}

// CustomiseFormula gives the tenant its own copy of one platform formula (the row, its bands and
// its split) so the tenant can change it. This is the only place a formula is copied, and it
// copies that one formula. From then on the tenant's copy replaces the platform row for the
// tenant; platform edits no longer reach it until the tenant reverts.
func (s *Service) CustomiseFormula(ctx context.Context, tenantID, platformFormulaID uuid.UUID) (*ent.PayrollFormula, error) {
	if s.IsPlatformTenant(tenantID) {
		return nil, fmt.Errorf("the platform tenant edits platform formulas directly")
	}
	src, err := s.visibleFormula(ctx, tenantID, platformFormulaID)
	if err != nil {
		return nil, err
	}
	if src.TenantID == tenantID {
		return nil, ErrAlreadyCustomised
	}
	exists, err := s.orm.PayrollFormula.Query().Where(
		payrollformula.TenantID(tenantID), payrollformula.TypeEQ(src.Type),
		payrollformula.CategoryEQ(src.Category), payrollformula.IsCurrent(true)).Exist(ctx)
	if err != nil {
		return nil, err
	}
	if exists {
		return nil, ErrAlreadyCustomised
	}
	items, err := s.FormulaItems(ctx, src.TenantID, src.ID)
	if err != nil {
		return nil, err
	}
	split, err := s.SplitRatio(ctx, src.TenantID, src.ID)
	if err != nil {
		return nil, err
	}
	in := FormulaInput{
		Type: src.Type, Category: src.Category, Title: src.Title, Unit: src.Unit,
		EffectiveFrom: src.EffectiveFrom, EffectiveTo: src.EffectiveTo, IsCurrent: true,
		Progressive: src.Progressive, PersonalRelief: src.PersonalRelief,
	}
	if src.RegulatorySource != nil {
		in.RegulatorySource = *src.RegulatorySource
	}
	for _, it := range items {
		in.Items = append(in.Items, FormulaItemInput{
			AmountFrom: it.AmountFrom, AmountTo: it.AmountTo,
			DeductAmount: it.DeductAmount, DeductPercentage: it.DeductPercentage,
		})
	}
	if split != nil {
		emp, empr := split.EmployeePercentage, split.EmployerPercentage
		in.EmployeePercentage, in.EmployerPercentage = &emp, &empr
	}
	return s.UpsertFormula(ctx, tenantID, in)
}

// RevertFormula removes the tenant's own versions of a formula's (type, category), with their
// bands and splits, so the tenant inherits the platform default again. formulaID may be the
// tenant row or the platform row of that key. Payslips already generated keep their amounts.
func (s *Service) RevertFormula(ctx context.Context, tenantID, formulaID uuid.UUID) (int, error) {
	if s.IsPlatformTenant(tenantID) {
		return 0, fmt.Errorf("platform formulas have nothing to revert to")
	}
	f, err := s.visibleFormula(ctx, tenantID, formulaID)
	if err != nil {
		return 0, err
	}
	ids, err := s.orm.PayrollFormula.Query().Where(
		payrollformula.TenantID(tenantID), payrollformula.TypeEQ(f.Type), payrollformula.CategoryEQ(f.Category)).IDs(ctx)
	if err != nil {
		return 0, err
	}
	if len(ids) == 0 {
		return 0, nil
	}
	return len(ids), s.deleteFormulas(ctx, tenantID, ids)
}

// DeleteFormula removes one formula row of the tenant (with its bands and split). A platform row
// is never deleted through a tenant: tenants revert instead.
func (s *Service) DeleteFormula(ctx context.Context, tenantID, formulaID uuid.UUID) error {
	f, err := s.visibleFormula(ctx, tenantID, formulaID)
	if err != nil {
		return err
	}
	if f.TenantID != tenantID {
		return ErrPlatformReadOnly
	}
	if s.IsPlatformTenant(tenantID) && f.IsCurrent {
		return fmt.Errorf("a current platform formula cannot be deleted: every tenant without its own version uses it")
	}
	return s.deleteFormulas(ctx, tenantID, []uuid.UUID{formulaID})
}

func (s *Service) deleteFormulas(ctx context.Context, tenantID uuid.UUID, ids []uuid.UUID) error {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.PayrollFormulaItem.Delete().Where(payrollformulaitem.TenantID(tenantID), payrollformulaitem.FormulaIDIn(ids...)).Exec(ctx); err != nil {
		return err
	}
	if _, err := tx.PayrollSplitRatio.Delete().Where(payrollsplitratio.TenantID(tenantID), payrollsplitratio.FormulaIDIn(ids...)).Exec(ctx); err != nil {
		return err
	}
	if _, err := tx.PayrollFormula.Delete().Where(payrollformula.TenantID(tenantID), payrollformula.IDIn(ids...)).Exec(ctx); err != nil {
		return err
	}
	return tx.Commit()
}

// formulaBands batch-loads the bands and splits of the given formulas (two queries, any owner in
// the tenant's scope).
func (s *Service) formulaBands(ctx context.Context, tenantID uuid.UUID, ids []uuid.UUID) (map[uuid.UUID][]*ent.PayrollFormulaItem, map[uuid.UUID]*ent.PayrollSplitRatio, error) {
	items := map[uuid.UUID][]*ent.PayrollFormulaItem{}
	splits := map[uuid.UUID]*ent.PayrollSplitRatio{}
	if len(ids) == 0 {
		return items, splits, nil
	}
	scope := s.scopeTenants(tenantID)
	rows, err := s.orm.PayrollFormulaItem.Query().
		Where(payrollformulaitem.TenantIDIn(scope...), payrollformulaitem.FormulaIDIn(ids...)).
		Order(ent.Asc(payrollformulaitem.FieldAmountFrom)).All(ctx)
	if err != nil {
		return nil, nil, err
	}
	for _, it := range rows {
		items[it.FormulaID] = append(items[it.FormulaID], it)
	}
	sp, err := s.orm.PayrollSplitRatio.Query().
		Where(payrollsplitratio.TenantIDIn(scope...), payrollsplitratio.FormulaIDIn(ids...)).All(ctx)
	if err != nil {
		return nil, nil, err
	}
	for _, r := range sp {
		if _, seen := splits[r.FormulaID]; !seen {
			splits[r.FormulaID] = r
		}
	}
	for id := range items {
		sort.SliceStable(items[id], func(i, j int) bool { return items[id][i].AmountFrom.LessThan(items[id][j].AmountFrom) })
	}
	return items, splits, nil
}
