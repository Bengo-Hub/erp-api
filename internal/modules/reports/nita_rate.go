package reports

import (
	"context"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// nitaConfiguredLevy is the monthly NITA levy per employee as configured for the tenant at the
// given period: the tenant's own deduction/nita formula, else the inherited platform formula,
// else the national default the payroll engine ships with. It is the same flat amount a payroll
// run charges, and it is only used for payslips that carry no itemised NITA line.
func (s *Service) nitaConfiguredLevy(ctx context.Context, tenantID uuid.UUID, period time.Time) decimal.Decimal {
	settings := payrollsettings.NewService(s.orm, s.systemTenant)
	if f, err := settings.EffectiveFormula(ctx, tenantID, "deduction", "nita", period); err == nil && f != nil {
		if items, ierr := settings.FormulaItems(ctx, f.TenantID, f.ID); ierr == nil && len(items) > 0 {
			rates := &payrollengine.FormulaRates{EmployerPercentage: decimal.NewFromInt(1)}
			for _, it := range items {
				to := it.AmountTo
				if to.IsZero() {
					to = payrollengine.Inf
				}
				rates.Bands = append(rates.Bands, payrollengine.Band{From: it.AmountFrom, To: to, Amount: it.DeductAmount})
			}
			if levy, cerr := payrollengine.CalculateNITA(rates); cerr == nil {
				return levy
			}
		}
	}
	levy, err := payrollengine.CalculateNITA(payrollengine.KRADefaults().NITA)
	if err != nil {
		return decimal.Zero
	}
	return levy
}
