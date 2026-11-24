package consumers

import (
	"context"
	"fmt"

	sharedevents "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

const treasuryStream = "treasury"

// claimSettler is the payroll service side of treasury claim settlement.
type claimSettler interface {
	SettleClaimByTreasury(ctx context.Context, tenantID, claimID uuid.UUID, in payroll.TreasurySettlement) (payroll.ClaimSettleOutcome, error)
	ReverseClaimTreasurySettlement(ctx context.Context, tenantID, claimID uuid.UUID) (payroll.ClaimSettleOutcome, error)
}

// TreasuryClaimConsumer consumes treasury.claim.settled (a payment voucher paid an expense claim:
// mark it paid) and treasury.claim.settlement_reversed (the voucher was reversed: mark it unpaid).
// Same delivery rules as the auth consumers: durable queue subscription per subject on the
// treasury stream, IdempotencyStore dedupe, explicit ack. The handlers are idempotent on their
// own as well, so a redelivery that slips past the store changes nothing.
type TreasuryClaimConsumer struct {
	log  *zap.Logger
	svc  claimSettler
	idem *sharedevents.IdempotencyStore
}

func NewTreasuryClaimConsumer(log *zap.Logger, svc *payroll.Service, idem *sharedevents.IdempotencyStore) *TreasuryClaimConsumer {
	return &TreasuryClaimConsumer{log: log.Named("consumers.treasury_claims"), svc: svc, idem: idem}
}

// Start ensures the treasury stream exists and registers the durable subscriptions.
func (c *TreasuryClaimConsumer) Start(ctx context.Context, nc *nats.Conn) error {
	if nc == nil {
		c.log.Warn("NATS not available; treasury claim consumers disabled")
		return nil
	}
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("treasury-claims: jetstream init: %w", err)
	}
	ensureStream(c.log, js, treasuryStream)
	subscribeAll(ctx, c.log, js, treasuryStream, c.idem, []subSpec{
		{"treasury.claim.settled", "erp-treasury-claim-settled", c.handleSettled},
		{"treasury.claim.settlement_reversed", "erp-treasury-claim-settlement-reversed", c.handleReversed},
	})
	return nil
}

// claimRef reads the tenant and claim of a settlement event. The claim id is the payload's
// claim_id, else the aggregate id. A payload tenant_id that disagrees with the envelope's tenant
// is refused, so one tenant's event never touches another tenant's claim.
func claimRef(evt *sharedevents.Event) (tenantID, claimID uuid.UUID, err error) {
	tenantID = tenantIDFromEvent(evt)
	if tenantID == uuid.Nil {
		return uuid.Nil, uuid.Nil, fmt.Errorf("%s: missing tenant id", evt.EventType)
	}
	if p := parseUUID(str(evt.Payload, "tenant_id")); p != uuid.Nil && p != tenantID {
		return uuid.Nil, uuid.Nil, fmt.Errorf("%s: payload tenant %s does not match event tenant %s", evt.EventType, p, tenantID)
	}
	claimID = parseUUID(str(evt.Payload, "claim_id"))
	if claimID == uuid.Nil {
		claimID = evt.AggregateID
	}
	if claimID == uuid.Nil {
		return uuid.Nil, uuid.Nil, fmt.Errorf("%s: missing claim id", evt.EventType)
	}
	return tenantID, claimID, nil
}

func (c *TreasuryClaimConsumer) handleSettled(ctx context.Context, evt *sharedevents.Event) error {
	tenantID, claimID, err := claimRef(evt)
	if err != nil {
		c.log.Error("claim settlement event dropped", zap.Error(err))
		return nil // malformed or cross-tenant: retrying cannot fix it
	}
	out, err := c.svc.SettleClaimByTreasury(ctx, tenantID, claimID, payroll.TreasurySettlement{
		Amount:        str(evt.Payload, "amount"),
		Currency:      str(evt.Payload, "currency"),
		VoucherNumber: str(evt.Payload, "voucher_number"),
		Reference:     str(evt.Payload, "reference"),
	})
	return c.logOutcome(evt, tenantID, claimID, out, err)
}

func (c *TreasuryClaimConsumer) handleReversed(ctx context.Context, evt *sharedevents.Event) error {
	tenantID, claimID, err := claimRef(evt)
	if err != nil {
		c.log.Error("claim settlement reversal dropped", zap.Error(err))
		return nil
	}
	out, err := c.svc.ReverseClaimTreasurySettlement(ctx, tenantID, claimID)
	return c.logOutcome(evt, tenantID, claimID, out, err)
}

// logOutcome logs the result. A claim this tenant does not have is acked (nothing to retry);
// any other error is returned so the message is redelivered.
func (c *TreasuryClaimConsumer) logOutcome(evt *sharedevents.Event, tenantID, claimID uuid.UUID, out payroll.ClaimSettleOutcome, err error) error {
	fields := []zap.Field{zap.String("event", evt.EventType), zap.String("tenant_id", tenantID.String()), zap.String("claim_id", claimID.String())}
	switch {
	case ent.IsNotFound(err):
		c.log.Warn("claim settlement event for an unknown claim", fields...)
		return nil
	case err != nil:
		return err
	case out == payroll.ClaimSettleCarried:
		c.log.Warn("treasury paid a claim that an unpaid payslip also carries; re-run the period before paying it", fields...)
	default:
		c.log.Info("claim settlement applied", append(fields, zap.String("outcome", string(out)))...)
	}
	return nil
}
