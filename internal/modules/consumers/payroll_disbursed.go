package consumers

import (
	"context"
	"fmt"
	"time"

	sharedevents "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
)

const treasuryStream = "treasury"

// PayrollDisbursedConsumer consumes treasury.payroll.disbursed and marks the batch's
// payslips published. Scoped by tenant AND outlet/batch_ref so one tenant's event can
// never publish another tenant's (or another outlet's) payslips (gaps §2.9). Idempotent
// via the IdempotencyStore (gaps §2.8).
type PayrollDisbursedConsumer struct {
	log  *zap.Logger
	orm  *ent.Client
	idem *sharedevents.IdempotencyStore
}

func NewPayrollDisbursedConsumer(log *zap.Logger, orm *ent.Client, idem *sharedevents.IdempotencyStore) *PayrollDisbursedConsumer {
	return &PayrollDisbursedConsumer{log: log.Named("consumers.payroll_disbursed"), orm: orm, idem: idem}
}

// Start ensures the treasury stream exists and registers the durable subscription.
func (c *PayrollDisbursedConsumer) Start(ctx context.Context, nc *nats.Conn) error {
	if nc == nil {
		c.log.Warn("NATS not available; payroll-disbursed consumer disabled")
		return nil
	}
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("payroll-disbursed: jetstream init: %w", err)
	}
	if _, err := js.StreamInfo(treasuryStream); err != nil {
		if _, addErr := js.AddStream(&nats.StreamConfig{
			Name:      treasuryStream,
			Subjects:  []string{"treasury.>"},
			Retention: nats.LimitsPolicy,
			MaxAge:    72 * time.Hour,
			Storage:   nats.FileStorage,
		}); addErr != nil && addErr != nats.ErrStreamNameAlreadyInUse {
			c.log.Warn("payroll-disbursed: ensure treasury stream failed", zap.Error(addErr))
		}
	}

	const durable = "erp-treasury-payroll-disbursed"
	sharedevents.SubscribeWithRebind(c.log, js, "treasury.payroll.disbursed", func(msg *nats.Msg) {
		evt, err := sharedevents.FromJSON(msg.Data)
		if err != nil {
			c.log.Error("payroll-disbursed: bad event", zap.Error(err))
			_ = msg.Ack()
			return
		}
		if c.idem != nil && evt.ID != uuid.Nil {
			if done, _ := c.idem.AlreadyProcessed(ctx, evt.ID, durable); done {
				_ = msg.Ack()
				return
			}
		}
		if err := c.handle(ctx, evt); err != nil {
			c.log.Error("payroll-disbursed: handler failed", zap.Error(err))
			_ = msg.Nak()
			return
		}
		if c.idem != nil && evt.ID != uuid.Nil {
			_ = c.idem.MarkProcessed(ctx, evt.ID, durable)
		}
		_ = msg.Ack()
	},
		nats.Durable(durable),
		nats.AckExplicit(),
		nats.AckWait(30*time.Second),
		nats.MaxDeliver(5),
		nats.DeliverAll(),
	)
	c.log.Info("payroll-disbursed: subscription active", zap.String("subject", "treasury.payroll.disbursed"))
	return nil
}

// handle marks the batch's payslips published. It prefers batch_ref (exact batch) and
// always enforces the event tenant — never crossing tenant boundaries.
func (c *PayrollDisbursedConsumer) handle(ctx context.Context, evt *sharedevents.Event) error {
	tenantID := tenantIDFromEvent(evt)
	if tenantID == uuid.Nil {
		return fmt.Errorf("payroll.disbursed missing tenant id")
	}
	batchRef := str(evt.Payload, "batch_ref")
	period := str(evt.Payload, "period")

	q := c.orm.Payslip.Update().Where(payslip.TenantID(tenantID))
	switch {
	case batchRef != "":
		q = q.Where(payslip.BatchRef(batchRef))
	case period != "":
		t, err := parsePeriod(period)
		if err != nil {
			return fmt.Errorf("payroll.disbursed bad period %q: %w", period, err)
		}
		q = q.Where(payslip.PaymentPeriod(t))
		if outlet := parseUUID(str(evt.Payload, "outlet_id")); outlet != uuid.Nil {
			q = q.Where(payslip.OutletID(outlet))
		}
	default:
		return fmt.Errorf("payroll.disbursed missing batch_ref and period")
	}

	n, err := q.SetPublished(true).Save(ctx)
	if err != nil {
		return fmt.Errorf("payroll.disbursed: mark published: %w", err)
	}
	c.log.Info("payroll.disbursed: marked payslips published",
		zap.Int("count", n), zap.String("tenant", tenantID.String()), zap.String("batch_ref", batchRef))
	return nil
}

// parsePeriod accepts YYYY-MM-DD or YYYY-MM (first of month).
func parsePeriod(s string) (time.Time, error) {
	if t, err := time.Parse("2006-01-02", s); err == nil {
		return t, nil
	}
	if t, err := time.Parse("2006-01", s); err == nil {
		return t, nil
	}
	return time.Time{}, fmt.Errorf("unrecognised period format")
}
