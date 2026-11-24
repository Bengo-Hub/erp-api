package payroll

import (
	"context"
	"fmt"
	"maps"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/expenseclaim"
)

// Claims treasury pays with a payment voucher (treasury.claim.settled) instead of a payroll run.
// The settlement is kept in the claim metadata under claimMetaTreasury, so a reversal
// (treasury.claim.settlement_reversed) reopens only a claim treasury paid, never one a payslip paid.
const claimMetaTreasury = "treasury_settlement"

// TreasurySettlement is what treasury reports about a voucher that paid a claim.
type TreasurySettlement struct {
	Amount        string
	Currency      string
	VoucherNumber string
	Reference     string
}

// ClaimSettleOutcome says what a treasury settlement event did to the claim.
type ClaimSettleOutcome string

const (
	ClaimSettleApplied ClaimSettleOutcome = "applied"
	// ClaimSettleNoop: the claim already holds this state (a redelivery, or paid by payroll).
	ClaimSettleNoop ClaimSettleOutcome = "noop"
	// ClaimSettleCarried: treasury paid a claim a payslip of an unpaid run also carries; the
	// period needs a re-run before it is paid or the employee is reimbursed twice.
	ClaimSettleCarried ClaimSettleOutcome = "carried_by_payslip"
)

// loadTenantClaim loads a claim of the tenant (not found for another tenant's claim).
func (s *Service) loadTenantClaim(ctx context.Context, tenantID, claimID uuid.UUID) (*ent.ExpenseClaim, error) {
	return s.orm.ExpenseClaim.Query().
		Where(expenseclaim.ID(claimID), expenseclaim.TenantID(tenantID)).Only(ctx)
}

// SettleClaimByTreasury marks a claim paid by a treasury payment voucher. A claim already paid
// is left as it is, so a redelivered event changes nothing.
func (s *Service) SettleClaimByTreasury(ctx context.Context, tenantID, claimID uuid.UUID, in TreasurySettlement) (ClaimSettleOutcome, error) {
	c, err := s.loadTenantClaim(ctx, tenantID, claimID)
	if err != nil {
		return "", err
	}
	if c.IsPaid {
		return ClaimSettleNoop, nil
	}
	meta := maps.Clone(c.Metadata)
	if meta == nil {
		meta = map[string]any{}
	}
	meta[claimMetaTreasury] = map[string]any{
		"amount": in.Amount, "currency": in.Currency,
		"voucher_number": in.VoucherNumber, "reference": in.Reference,
	}
	if err := c.Update().SetIsPaid(true).SetPaymentDate(time.Now().UTC()).SetMetadata(meta).Exec(ctx); err != nil {
		return "", fmt.Errorf("payroll: settle claim: %w", err)
	}
	if linked, _ := c.Metadata[claimMetaPayslip].(string); linked != "" {
		return ClaimSettleCarried, nil
	}
	return ClaimSettleApplied, nil
}

// ReverseClaimTreasurySettlement reopens a claim whose treasury voucher was reversed. Only a
// claim treasury settled is reopened: one paid through a payslip stays paid.
func (s *Service) ReverseClaimTreasurySettlement(ctx context.Context, tenantID, claimID uuid.UUID) (ClaimSettleOutcome, error) {
	c, err := s.loadTenantClaim(ctx, tenantID, claimID)
	if err != nil {
		return "", err
	}
	if _, ok := c.Metadata[claimMetaTreasury]; !ok || !c.IsPaid {
		return ClaimSettleNoop, nil
	}
	meta := maps.Clone(c.Metadata)
	delete(meta, claimMetaTreasury)
	if err := c.Update().SetIsPaid(false).ClearPaymentDate().SetMetadata(meta).Exec(ctx); err != nil {
		return "", fmt.Errorf("payroll: reverse claim settlement: %w", err)
	}
	return ClaimSettleApplied, nil
}
