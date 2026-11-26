package payrollsettings

import (
	"context"
	"encoding/json"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformulaitem"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollsplitratio"
	"github.com/Bengo-Hub/erp-api/internal/ent/schema"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// FormulaItemInput is one band/bracket of a formula (percentages are stored as e.g. 30.00 = 30%).
type FormulaItemInput struct {
	AmountFrom       decimal.Decimal
	AmountTo         decimal.Decimal // 0 == +Inf (open-ended top band)
	DeductAmount     decimal.Decimal
	DeductPercentage decimal.Decimal
}

// FormulaInput is the create/update payload for a formula + its bands + employee/employer split.
type FormulaInput struct {
	ID               *uuid.UUID // nil = create
	Type             string
	Category         string
	Title            string
	Unit             string
	EffectiveFrom    *time.Time
	EffectiveTo      *time.Time
	IsCurrent        bool
	Progressive      bool
	PersonalRelief   decimal.Decimal
	RegulatorySource string
	Items            []FormulaItemInput
	// Split is applied when either percentage is set; nil leaves the category default in effect.
	EmployeePercentage *decimal.Decimal
	EmployerPercentage *decimal.Decimal
	// MinimumContribution is the least employee contribution per month (SHIF: KES 300), kept in
	// the formula's metadata. Nil keeps the stored value on update and sets none on create; zero
	// removes it.
	MinimumContribution *decimal.Decimal
	// DeductionOrder is copied onto a new version (customise, sync, corrections); ignored on update.
	DeductionOrder []schema.DeductionPhase
}

// metaMinimumContribution is the formula metadata key of the minimum monthly contribution.
const metaMinimumContribution = "minimum_contribution"

// Dated rules kept as formula rows (versioned by effective dates, overridable per tenant) whose
// values live in the metadata.
const (
	FormulaTypeReliefAllowance = "relief_allowance"
	FormulaCategoryPerDiem     = "per_diem"
	// MetaDailyExempt is the tax-free per diem per day (Income Tax Act s.5(2)(a)(iii)).
	MetaDailyExempt = "daily_exempt"

	FormulaTypeFBT     = "fbt"
	FormulaCategoryFBT = "fbt"
	// MetaFBTTaxRate is the fringe benefit tax rate as a fraction (s.12B: the resident corporate
	// rate, Third Schedule para 15).
	MetaFBTTaxRate = "tax_rate"
	// MetaMarketInterestRate is KRA's market interest rate for the quarter, in percent.
	MetaMarketInterestRate = "market_interest_rate"
)

// FormulaMinimumContribution reads a formula's minimum monthly contribution from its metadata
// (zero when unset or unreadable).
func FormulaMinimumContribution(f *ent.PayrollFormula) decimal.Decimal {
	if f == nil || f.Metadata == nil {
		return decimal.Zero
	}
	return metaDecimal(f.Metadata[metaMinimumContribution])
}

// hasMinimumContribution reports whether the formula records a minimum (zero counts).
func hasMinimumContribution(f *ent.PayrollFormula) bool {
	_, ok := f.Metadata[metaMinimumContribution]
	return ok
}

// RecordedMinimumContribution is the formula's own minimum, or nil when it records none.
func RecordedMinimumContribution(f *ent.PayrollFormula) *decimal.Decimal {
	if !hasMinimumContribution(f) {
		return nil
	}
	m := FormulaMinimumContribution(f)
	return &m
}

// metaDecimal reads a decimal stored in a JSON metadata map as a string or a number.
func metaDecimal(v any) decimal.Decimal {
	switch x := v.(type) {
	case string:
		if d, err := decimal.NewFromString(x); err == nil {
			return d
		}
	case float64:
		return decimal.NewFromFloat(x)
	case json.Number:
		if d, err := decimal.NewFromString(x.String()); err == nil {
			return d
		}
	}
	return decimal.Zero
}

// withMinimumContribution returns metadata with the minimum set, leaving every other key as it
// was. Zero is stored too, so a minimum someone removed on purpose is not seeded back.
func withMinimumContribution(meta map[string]any, min decimal.Decimal) map[string]any {
	out := map[string]any{}
	for k, v := range meta {
		out[k] = v
	}
	out[metaMinimumContribution] = min.StringFixed(2)
	return out
}

// EnsureSHIFMinimum gives every platform SHIF formula version without a minimum contribution the
// statutory KES 300 (payrollengine.SHIFMinimumContribution). Idempotent: a version that already
// records a minimum, including zero, is left alone. Tenant versions are never touched: a
// tenant version without a recorded minimum inherits the platform's. Returns how many changed.
func EnsureSHIFMinimum(ctx context.Context, orm *ent.Client, systemTenant uuid.UUID) (int, error) {
	rows, err := orm.PayrollFormula.Query().Where(
		payrollformula.TenantID(systemTenant), payrollformula.TypeEQ("deduction"),
		payrollformula.CategoryEQ("shif")).All(ctx)
	if err != nil {
		return 0, err
	}
	n := 0
	for _, f := range rows {
		if _, ok := f.Metadata[metaMinimumContribution]; ok {
			continue
		}
		if err := f.Update().SetMetadata(withMinimumContribution(f.Metadata, payrollengine.SHIFMinimumContribution)).Exec(ctx); err != nil {
			return n, err
		}
		n++
	}
	return n, nil
}

// FormulaDetail is the full read model: the formula row + its bands + split ratio.
type FormulaDetail struct {
	Formula *ent.PayrollFormula
	Items   []*ent.PayrollFormulaItem
	Split   *ent.PayrollSplitRatio
}

// GetFormulaDetail returns a formula the tenant can read (its own or an inherited platform row)
// with its bands and split ratio.
func (s *Service) GetFormulaDetail(ctx context.Context, tenantID, formulaID uuid.UUID) (*FormulaDetail, error) {
	f, err := s.visibleFormula(ctx, tenantID, formulaID)
	if err != nil {
		return nil, err
	}
	items, err := s.FormulaItems(ctx, f.TenantID, formulaID)
	if err != nil {
		return nil, err
	}
	split, _ := s.SplitRatio(ctx, f.TenantID, formulaID) // optional
	return &FormulaDetail{Formula: f, Items: items, Split: split}, nil
}

// UpsertFormula creates or updates a formula of tenantID together with its bands and split ratio
// in one transaction. An update must target a row the tenant owns (a platform row is changed only
// with tenantID set to the platform tenant). When IsCurrent is set, the other current formula of
// the same (tenant, type, category) is demoted first so the partial unique "one current per
// (tenant, type, category)" invariant holds; when the new version has a start date, the demoted
// version is closed the day before it so earlier months keep resolving to it. Bands are replaced
// wholesale; the split is replaced when provided.
func (s *Service) UpsertFormula(ctx context.Context, tenantID uuid.UUID, in FormulaInput) (*ent.PayrollFormula, error) {
	if in.Type == "" || in.Title == "" {
		return nil, fmt.Errorf("type and title are required")
	}
	if in.EffectiveFrom != nil && in.EffectiveTo != nil && in.EffectiveTo.Before(*in.EffectiveFrom) {
		return nil, fmt.Errorf("effective_to is before effective_from")
	}
	if in.MinimumContribution != nil && in.MinimumContribution.IsNegative() {
		return nil, fmt.Errorf("minimum contribution cannot be negative")
	}
	for i, it := range in.Items {
		if it.AmountFrom.IsNegative() || it.AmountTo.IsNegative() || it.DeductAmount.IsNegative() || it.DeductPercentage.IsNegative() {
			return nil, fmt.Errorf("band %d: amounts and percentages cannot be negative", i+1)
		}
		if !it.AmountTo.IsZero() && it.AmountTo.LessThan(it.AmountFrom) {
			return nil, fmt.Errorf("band %d: upper bound is below the lower bound", i+1)
		}
	}
	if in.ID != nil {
		owned, err := s.orm.PayrollFormula.Query().
			Where(payrollformula.ID(*in.ID), payrollformula.TenantID(tenantID)).Exist(ctx)
		if err != nil {
			return nil, err
		}
		if !owned {
			return nil, ErrPlatformReadOnly
		}
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()

	// Demote the existing current formula of the same (tenant,type,category) before promoting this one.
	if in.IsCurrent {
		q := tx.PayrollFormula.Query().
			Where(
				payrollformula.TenantID(tenantID),
				payrollformula.TypeEQ(in.Type),
				payrollformula.CategoryEQ(in.Category),
				payrollformula.IsCurrent(true),
			)
		if in.ID != nil {
			q = q.Where(payrollformula.IDNEQ(*in.ID))
		}
		olds, err := q.All(ctx)
		if err != nil {
			return nil, fmt.Errorf("demote current: %w", err)
		}
		for _, old := range olds {
			u := old.Update().SetIsCurrent(false)
			if in.EffectiveFrom != nil && old.EffectiveTo == nil &&
				(old.EffectiveFrom == nil || old.EffectiveFrom.Before(*in.EffectiveFrom)) {
				u = u.SetEffectiveTo(in.EffectiveFrom.AddDate(0, 0, -1))
			}
			if _, err := u.Save(ctx); err != nil {
				return nil, fmt.Errorf("demote current: %w", err)
			}
		}
	}

	var formula *ent.PayrollFormula
	if in.ID == nil {
		c := tx.PayrollFormula.Create().
			SetTenantID(tenantID).
			SetType(in.Type).
			SetCategory(in.Category).
			SetTitle(in.Title).
			SetUnit(orDefault(in.Unit, "KES")).
			SetIsCurrent(in.IsCurrent).
			SetProgressive(in.Progressive).
			SetPersonalRelief(in.PersonalRelief)
		if in.EffectiveFrom != nil {
			c = c.SetEffectiveFrom(*in.EffectiveFrom)
		}
		if in.EffectiveTo != nil {
			c = c.SetEffectiveTo(*in.EffectiveTo)
		}
		if in.RegulatorySource != "" {
			c = c.SetRegulatorySource(in.RegulatorySource)
		}
		if in.MinimumContribution != nil {
			c = c.SetMetadata(withMinimumContribution(nil, *in.MinimumContribution))
		}
		if len(in.DeductionOrder) > 0 {
			c = c.SetDeductionOrder(in.DeductionOrder)
		}
		formula, err = c.Save(ctx)
	} else {
		u := tx.PayrollFormula.UpdateOneID(*in.ID).
			SetTitle(in.Title).
			SetCategory(in.Category).
			SetUnit(orDefault(in.Unit, "KES")).
			SetIsCurrent(in.IsCurrent).
			SetProgressive(in.Progressive).
			SetPersonalRelief(in.PersonalRelief)
		if in.EffectiveFrom != nil {
			u = u.SetEffectiveFrom(*in.EffectiveFrom)
		}
		if in.EffectiveTo != nil {
			u = u.SetEffectiveTo(*in.EffectiveTo)
		}
		if in.RegulatorySource != "" {
			u = u.SetRegulatorySource(in.RegulatorySource)
		}
		if in.MinimumContribution != nil {
			cur, gerr := tx.PayrollFormula.Get(ctx, *in.ID)
			if gerr != nil {
				return nil, fmt.Errorf("load formula: %w", gerr)
			}
			u = u.SetMetadata(withMinimumContribution(cur.Metadata, *in.MinimumContribution))
		}
		formula, err = u.Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("save formula: %w", err)
	}

	// Replace bands.
	if _, err := tx.PayrollFormulaItem.Delete().
		Where(payrollformulaitem.TenantID(tenantID), payrollformulaitem.FormulaID(formula.ID)).Exec(ctx); err != nil {
		return nil, fmt.Errorf("clear bands: %w", err)
	}
	for _, it := range in.Items {
		if _, err := tx.PayrollFormulaItem.Create().
			SetTenantID(tenantID).
			SetFormulaID(formula.ID).
			SetAmountFrom(it.AmountFrom).
			SetAmountTo(it.AmountTo).
			SetDeductAmount(it.DeductAmount).
			SetDeductPercentage(it.DeductPercentage).
			Save(ctx); err != nil {
			return nil, fmt.Errorf("save band: %w", err)
		}
	}

	// Replace split when provided.
	if in.EmployeePercentage != nil || in.EmployerPercentage != nil {
		if _, err := tx.PayrollSplitRatio.Delete().
			Where(payrollsplitratio.TenantID(tenantID), payrollsplitratio.FormulaID(formula.ID)).Exec(ctx); err != nil {
			return nil, fmt.Errorf("clear split: %w", err)
		}
		emp := decimal.NewFromInt(100)
		if in.EmployeePercentage != nil {
			emp = *in.EmployeePercentage
		}
		empr := decimal.Zero
		if in.EmployerPercentage != nil {
			empr = *in.EmployerPercentage
		}
		if _, err := tx.PayrollSplitRatio.Create().
			SetTenantID(tenantID).
			SetFormulaID(formula.ID).
			SetEmployeePercentage(emp).
			SetEmployerPercentage(empr).
			Save(ctx); err != nil {
			return nil, fmt.Errorf("save split: %w", err)
		}
	}

	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return formula, nil
}

func orDefault(v, def string) string {
	if v == "" {
		return def
	}
	return v
}
