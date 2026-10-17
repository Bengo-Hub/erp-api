// Package payrollsettings owns the ERP's tenant-scoped statutory rate tables (PAYE,
// NSSF, SHIF/NHIF, housing, relief) and resolves them into a payrollengine.Config.
// Rates are NEVER read from treasury.
package payrollsettings

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformulaitem"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollsplitratio"
)

// Service provides CRUD + resolution over the payroll-settings tables.
type Service struct {
	orm *ent.Client
	// systemTenant is the default-tenant whose rows are the inherited KRA national
	// defaults; tenants without their own current formula fall back to it.
	systemTenant uuid.UUID
}

// NewService builds the settings service. systemTenant is uuid.Nil-safe (falls back to
// per-tenant only when zero).
func NewService(orm *ent.Client, systemTenant uuid.UUID) *Service {
	return &Service{orm: orm, systemTenant: systemTenant}
}

// ListFormulas returns tenant-scoped formulas, newest-effective first.
func (s *Service) ListFormulas(ctx context.Context, tenantID uuid.UUID) ([]*ent.PayrollFormula, error) {
	return s.orm.PayrollFormula.Query().
		Where(payrollformula.TenantID(tenantID)).
		Order(ent.Desc(payrollformula.FieldEffectiveFrom)).
		All(ctx)
}

// EffectiveFormula resolves the single current+effective formula for (type, category) at
// the given period, preferring the tenant's own rows then the system defaults. Returns a
// typed error if none is configured (fail-loud).
func (s *Service) EffectiveFormula(ctx context.Context, tenantID uuid.UUID, ftype, category string, period time.Time) (*ent.PayrollFormula, error) {
	f, err := s.effectiveFor(ctx, tenantID, ftype, category, period)
	if err == nil && f != nil {
		return f, nil
	}
	if s.systemTenant != uuid.Nil && s.systemTenant != tenantID {
		if f, err2 := s.effectiveFor(ctx, s.systemTenant, ftype, category, period); err2 == nil && f != nil {
			return f, nil
		}
	}
	return nil, fmt.Errorf("payrollsettings: no current %s/%s formula effective at %s", ftype, category, period.Format("2006-01-02"))
}

// effectiveFor finds a current formula matching type/category effective for period within
// one tenant.
func (s *Service) effectiveFor(ctx context.Context, tenantID uuid.UUID, ftype, category string, period time.Time) (*ent.PayrollFormula, error) {
	q := s.orm.PayrollFormula.Query().Where(
		payrollformula.TenantID(tenantID),
		payrollformula.TypeEQ(ftype),
		payrollformula.IsCurrent(true),
	)
	if category != "" {
		q = q.Where(payrollformula.Category(category))
	}
	rows, err := q.Order(ent.Desc(payrollformula.FieldEffectiveFrom)).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, f := range rows {
		if isEffective(f, period) {
			return f, nil
		}
	}
	// no date-bounded match; fall back to a current row with open bounds
	for _, f := range rows {
		if f.EffectiveFrom == nil {
			return f, nil
		}
	}
	if len(rows) > 0 {
		return rows[0], nil
	}
	return nil, fmt.Errorf("not found")
}

func isEffective(f *ent.PayrollFormula, period time.Time) bool {
	if f.EffectiveFrom == nil {
		return false
	}
	if period.Before(*f.EffectiveFrom) {
		return false
	}
	if f.EffectiveTo != nil && period.After(*f.EffectiveTo) {
		return false
	}
	return true
}

// FormulaItems returns the bands of a formula (ascending amount_from).
func (s *Service) FormulaItems(ctx context.Context, tenantID, formulaID uuid.UUID) ([]*ent.PayrollFormulaItem, error) {
	return s.orm.PayrollFormulaItem.Query().
		Where(payrollformulaitem.TenantID(tenantID), payrollformulaitem.FormulaID(formulaID)).
		Order(ent.Asc(payrollformulaitem.FieldAmountFrom)).
		All(ctx)
}

// SplitRatio returns the employee/employer split for a formula (or nil).
func (s *Service) SplitRatio(ctx context.Context, tenantID, formulaID uuid.UUID) (*ent.PayrollSplitRatio, error) {
	r, err := s.orm.PayrollSplitRatio.Query().
		Where(payrollsplitratio.TenantID(tenantID), payrollsplitratio.FormulaID(formulaID)).
		First(ctx)
	if ent.IsNotFound(err) {
		return nil, nil
	}
	return r, err
}
