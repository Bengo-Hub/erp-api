package payroll

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// ensureRepayOption creates (or reuses) a RepayOption for an installment plan and returns its id.
// installment_amount is computed = amount / no_of_installments (the schema's documented invariant).
// Returns (nil, nil) when no installment plan is requested (amount<=0 or installments<=1 means a
// single lump-sum recovery, which needs no plan). When an existing optionID is passed it is updated
// in place so editing a record's installment count doesn't orphan the row.
func (s *Service) ensureRepayOption(ctx context.Context, tenantID uuid.UUID, optionID *uuid.UUID, amount decimal.Decimal, installments int) (*uuid.UUID, error) {
	if installments <= 1 || amount.LessThanOrEqual(decimal.Zero) {
		return optionID, nil // keep any existing option; no new plan needed
	}
	per := amount.DivRound(decimal.NewFromInt(int64(installments)), 4)
	if optionID != nil {
		updated, err := s.orm.RepayOption.UpdateOneID(*optionID).
			SetAmount(amount).
			SetNoOfInstallments(installments).
			SetInstallmentAmount(per).
			Save(ctx)
		if err == nil {
			id := updated.ID
			return &id, nil
		}
		if !ent.IsNotFound(err) {
			return nil, fmt.Errorf("payroll: update repay option: %w", err)
		}
		// fallthrough to create when the referenced option no longer exists
	}
	ro, err := s.orm.RepayOption.Create().
		SetTenantID(tenantID).
		SetAmount(amount).
		SetNoOfInstallments(installments).
		SetInstallmentAmount(per).
		Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("payroll: create repay option: %w", err)
	}
	id := ro.ID
	return &id, nil
}

// GetRepayOption returns a tenant-scoped repay option (for the schedule preview / view).
func (s *Service) GetRepayOption(ctx context.Context, id uuid.UUID) (*ent.RepayOption, error) {
	return s.orm.RepayOption.Get(ctx, id)
}
