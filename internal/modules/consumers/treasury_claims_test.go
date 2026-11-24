package consumers

import (
	"context"
	"errors"
	"testing"

	sharedevents "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

type settleCall struct {
	op               string
	tenant, claim    uuid.UUID
	voucher, ref, am string
}

type fakeSettler struct {
	calls []settleCall
	err   error
	out   payroll.ClaimSettleOutcome
}

func (f *fakeSettler) SettleClaimByTreasury(_ context.Context, tenantID, claimID uuid.UUID, in payroll.TreasurySettlement) (payroll.ClaimSettleOutcome, error) {
	f.calls = append(f.calls, settleCall{"settle", tenantID, claimID, in.VoucherNumber, in.Reference, in.Amount})
	return f.out, f.err
}

func (f *fakeSettler) ReverseClaimTreasurySettlement(_ context.Context, tenantID, claimID uuid.UUID) (payroll.ClaimSettleOutcome, error) {
	f.calls = append(f.calls, settleCall{op: "reverse", tenant: tenantID, claim: claimID})
	return f.out, f.err
}

func settlementEvent(eventType string, tenant, claim uuid.UUID, payloadTenant string) *sharedevents.Event {
	return sharedevents.NewEvent(eventType, "treasury", claim, tenant, map[string]any{
		"tenant_id": payloadTenant, "claim_id": claim.String(), "amount": "900.00", "currency": "KES",
		"voucher_number": "PV-0007", "reference": "MPESA123",
	})
}

func TestTreasuryClaimConsumer_SettledAndReversed(t *testing.T) {
	f := &fakeSettler{out: payroll.ClaimSettleApplied}
	c := &TreasuryClaimConsumer{log: zap.NewNop(), svc: f}
	tenant, claim := uuid.New(), uuid.New()

	if err := c.handleSettled(context.Background(), settlementEvent("claim.settled", tenant, claim, tenant.String())); err != nil {
		t.Fatal(err)
	}
	if err := c.handleReversed(context.Background(), settlementEvent("claim.settlement_reversed", tenant, claim, tenant.String())); err != nil {
		t.Fatal(err)
	}
	want := []settleCall{
		{"settle", tenant, claim, "PV-0007", "MPESA123", "900.00"},
		{op: "reverse", tenant: tenant, claim: claim},
	}
	if len(f.calls) != 2 || f.calls[0] != want[0] || f.calls[1] != want[1] {
		t.Fatalf("calls = %+v, want %+v", f.calls, want)
	}
}

// The claim id falls back to the aggregate id when the payload omits it.
func TestTreasuryClaimConsumer_ClaimFromAggregate(t *testing.T) {
	f := &fakeSettler{out: payroll.ClaimSettleApplied}
	c := &TreasuryClaimConsumer{log: zap.NewNop(), svc: f}
	tenant, claim := uuid.New(), uuid.New()
	evt := sharedevents.NewEvent("claim.settled", "treasury", claim, tenant, map[string]any{"amount": "1.00"})
	if err := c.handleSettled(context.Background(), evt); err != nil {
		t.Fatal(err)
	}
	if len(f.calls) != 1 || f.calls[0].claim != claim || f.calls[0].tenant != tenant {
		t.Fatalf("calls = %+v", f.calls)
	}
}

// A payload tenant that disagrees with the envelope, or a missing tenant, is dropped (acked)
// without touching any claim.
func TestTreasuryClaimConsumer_TenantChecked(t *testing.T) {
	f := &fakeSettler{out: payroll.ClaimSettleApplied}
	c := &TreasuryClaimConsumer{log: zap.NewNop(), svc: f}
	claim := uuid.New()
	if err := c.handleSettled(context.Background(), settlementEvent("claim.settled", uuid.New(), claim, uuid.New().String())); err != nil {
		t.Fatalf("mismatched tenant: err = %v, want nil (dropped)", err)
	}
	if err := c.handleReversed(context.Background(), settlementEvent("claim.settlement_reversed", uuid.Nil, claim, "")); err != nil {
		t.Fatalf("missing tenant: err = %v, want nil (dropped)", err)
	}
	if len(f.calls) != 0 {
		t.Fatalf("a cross-tenant or tenantless event reached the service: %+v", f.calls)
	}
}

// An unknown claim is acked; a store error is returned so the message is redelivered.
func TestTreasuryClaimConsumer_Errors(t *testing.T) {
	tenant, claim := uuid.New(), uuid.New()
	nf := &TreasuryClaimConsumer{log: zap.NewNop(), svc: &fakeSettler{err: &ent.NotFoundError{}}}
	if err := nf.handleSettled(context.Background(), settlementEvent("claim.settled", tenant, claim, tenant.String())); err != nil {
		t.Fatalf("unknown claim: err = %v, want nil", err)
	}
	boom := errors.New("db down")
	fail := &TreasuryClaimConsumer{log: zap.NewNop(), svc: &fakeSettler{err: boom}}
	if err := fail.handleSettled(context.Background(), settlementEvent("claim.settled", tenant, claim, tenant.String())); !errors.Is(err, boom) {
		t.Fatalf("store error: err = %v, want it returned for redelivery", err)
	}
}
