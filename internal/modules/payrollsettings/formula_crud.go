package payrollsettings

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformulaitem"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollsplitratio"
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
}

// FormulaDetail is the full read model: the formula row + its bands + split ratio.
type FormulaDetail struct {
	Formula *ent.PayrollFormula
	Items   []*ent.PayrollFormulaItem
	Split   *ent.PayrollSplitRatio
}

// GetFormulaDetail returns a tenant-scoped formula with its bands + split ratio.
func (s *Service) GetFormulaDetail(ctx context.Context, tenantID, formulaID uuid.UUID) (*FormulaDetail, error) {
	f, err := s.orm.PayrollFormula.Query().
		Where(payrollformula.TenantID(tenantID), payrollformula.ID(formulaID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	items, err := s.FormulaItems(ctx, tenantID, formulaID)
	if err != nil {
		return nil, err
	}
	split, _ := s.SplitRatio(ctx, tenantID, formulaID) // optional
	return &FormulaDetail{Formula: f, Items: items, Split: split}, nil
}

// UpsertFormula creates or updates a formula together with its bands and split ratio in one
// transaction. When IsCurrent is set, any other current formula for the same (tenant, type,
// category) is demoted first so the partial-unique "one current per (tenant,type,category)"
// invariant holds. Bands are replaced wholesale; the split is replaced when provided.
func (s *Service) UpsertFormula(ctx context.Context, tenantID uuid.UUID, in FormulaInput) (*ent.PayrollFormula, error) {
	if in.Type == "" || in.Title == "" {
		return nil, fmt.Errorf("type and title are required")
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()

	// Demote the existing current formula of the same (tenant,type,category) before promoting this one.
	if in.IsCurrent {
		demote := tx.PayrollFormula.Update().
			Where(
				payrollformula.TenantID(tenantID),
				payrollformula.TypeEQ(in.Type),
				payrollformula.CategoryEQ(in.Category),
				payrollformula.IsCurrent(true),
			)
		if in.ID != nil {
			demote = demote.Where(payrollformula.IDNEQ(*in.ID))
		}
		if _, err := demote.SetIsCurrent(false).Save(ctx); err != nil {
			return nil, fmt.Errorf("demote current: %w", err)
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
