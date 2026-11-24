// Package payrollsettings owns the ERP's payroll configuration: the statutory rate tables (PAYE,
// NSSF, SHIF/NHIF, housing levy, NITA), the KRA reliefs and the earnings, deductions and benefits
// catalogue, and resolves them into a payrollengine.Config.
//
// Configuration is defined once at platform level (rows of the system tenant) and inherited by
// every tenant; a tenant customises only what it needs (resolver.go, reliefs.go, components.go).
// Approved statutory rate changes published by treasury-api are applied to the platform rows only
// (treasury_sync.go); the engine never calls treasury during a run.
package payrollsettings

import (
	"context"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformulaitem"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollsplitratio"
)

// Service provides CRUD and resolution over the payroll-settings tables.
type Service struct {
	orm *ent.Client
	// systemTenant owns the platform rows (statutory formulas, reliefs, component catalogue)
	// that every tenant inherits.
	systemTenant uuid.UUID
}

// NewService builds the settings service. A zero systemTenant disables inheritance (each tenant
// then sees only its own rows).
func NewService(orm *ent.Client, systemTenant uuid.UUID) *Service {
	return &Service{orm: orm, systemTenant: systemTenant}
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
