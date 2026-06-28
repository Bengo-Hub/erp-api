package consumers

import (
	"context"
	"fmt"
	"strings"
	"time"

	sharedevents "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"
	"github.com/nats-io/nats.go"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/services/usersync"
)

const authStream = "auth"

// TenantSyncConsumer consumes auth.tenant.> and auth.outlet.> events and upserts the
// local AuthTenant / AuthOutlet shadows. Port of integrations/tenant_sync.py consumers.
//
// Uses an explicit consumer registry (durable per subject) + IdempotencyStore so a
// missing module import can never silently drop handlers (fixes gaps §3), and redelivery
// is deduped.
type TenantSyncConsumer struct {
	log    *zap.Logger
	syncer *usersync.TenantSyncer
	idem   *sharedevents.IdempotencyStore
}

func NewTenantSyncConsumer(log *zap.Logger, syncer *usersync.TenantSyncer, idem *sharedevents.IdempotencyStore) *TenantSyncConsumer {
	return &TenantSyncConsumer{
		log:    log.Named("consumers.tenant_sync"),
		syncer: syncer,
		idem:   idem,
	}
}

type subSpec struct {
	subject string
	durable string
	handler func(context.Context, *sharedevents.Event) error
}

// Start ensures the auth stream exists and registers durable subscriptions.
func (c *TenantSyncConsumer) Start(ctx context.Context, nc *nats.Conn) error {
	if nc == nil {
		c.log.Warn("NATS not available; tenant-sync consumers disabled")
		return nil
	}
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("tenant-sync: jetstream init: %w", err)
	}

	// Guard against a startup race with auth-api: ensure the auth stream exists.
	if _, err := js.StreamInfo(authStream); err != nil {
		if _, addErr := js.AddStream(&nats.StreamConfig{
			Name:      authStream,
			Subjects:  []string{"auth.>"},
			Retention: nats.LimitsPolicy,
			MaxAge:    72 * time.Hour,
			Storage:   nats.FileStorage,
		}); addErr != nil && addErr != nats.ErrStreamNameAlreadyInUse {
			c.log.Warn("tenant-sync: ensure auth stream failed", zap.Error(addErr))
		}
	}

	specs := []subSpec{
		{"auth.tenant.>", "erp-auth-tenant", c.handleTenantEvent},
		{"auth.outlet.>", "erp-auth-outlet", c.handleOutletEvent},
	}

	for _, s := range specs {
		s := s
		consumerName := s.durable
		sharedevents.SubscribeQueueWithRebind(c.log, js, authStream, s.subject, s.durable, func(msg *nats.Msg) {
			evt, err := sharedevents.FromJSON(msg.Data)
			if err != nil {
				c.log.Error("tenant-sync: bad event", zap.String("subject", s.subject), zap.Error(err))
				_ = msg.Ack() // poison message: drop, don't redeliver forever
				return
			}
			// Idempotency: skip if already processed by this consumer.
			if c.idem != nil && evt.ID != uuid.Nil {
				if done, _ := c.idem.AlreadyProcessed(ctx, evt.ID, consumerName); done {
					_ = msg.Ack()
					return
				}
			}
			if err := s.handler(ctx, evt); err != nil {
				c.log.Error("tenant-sync: handler failed", zap.String("subject", s.subject), zap.Error(err))
				_ = msg.Nak()
				return
			}
			if c.idem != nil && evt.ID != uuid.Nil {
				_ = c.idem.MarkProcessed(ctx, evt.ID, consumerName)
			}
			_ = msg.Ack()
		},
			nats.Durable(s.durable),
			nats.AckExplicit(),
			nats.AckWait(30*time.Second),
			nats.MaxDeliver(5),
			nats.DeliverAll(),
		)
		c.log.Info("tenant-sync: subscription active", zap.String("subject", s.subject), zap.String("durable", s.durable))
	}
	return nil
}

func (c *TenantSyncConsumer) handleTenantEvent(ctx context.Context, evt *sharedevents.Event) error {
	id := tenantIDFromEvent(evt)
	if id == uuid.Nil {
		return fmt.Errorf("auth.tenant event missing tenant id")
	}
	in := usersync.TenantInput{
		ID:         id,
		Slug:       str(evt.Payload, "slug"),
		Name:       str(evt.Payload, "name"),
		Status:     str(evt.Payload, "status"),
		IsPlatform: boolean(evt.Payload, "is_platform"),
	}
	if _, err := c.syncer.UpsertTenant(ctx, in); err != nil {
		return err
	}
	c.log.Info("tenant shadow upserted", zap.String("tenant_id", id.String()), zap.String("event", evt.EventType))
	return nil
}

func (c *TenantSyncConsumer) handleOutletEvent(ctx context.Context, evt *sharedevents.Event) error {
	outletID := parseUUID(str(evt.Payload, "id"))
	if outletID == uuid.Nil {
		outletID = parseUUID(str(evt.Payload, "outlet_id"))
	}
	if outletID == uuid.Nil {
		return fmt.Errorf("auth.outlet event missing outlet id")
	}

	if strings.HasSuffix(evt.EventType, "archived") {
		return c.syncer.ArchiveOutlet(ctx, outletID)
	}

	tenantID := tenantIDFromEvent(evt)
	if tenantID == uuid.Nil {
		return fmt.Errorf("auth.outlet event missing tenant id")
	}
	in := usersync.OutletInput{
		ID:       outletID,
		TenantID: tenantID,
		Code:     str(evt.Payload, "code"),
		Name:     str(evt.Payload, "name"),
		UseCase:  str(evt.Payload, "use_case"),
		IsHQ:     boolean(evt.Payload, "is_hq"),
		Status:   str(evt.Payload, "status"),
		Timezone: str(evt.Payload, "timezone"),
	}
	if _, err := c.syncer.UpsertOutlet(ctx, in); err != nil {
		return err
	}
	c.log.Info("outlet shadow upserted", zap.String("outlet_id", outletID.String()), zap.String("event", evt.EventType))
	return nil
}

// --- payload helpers ---

func tenantIDFromEvent(evt *sharedevents.Event) uuid.UUID {
	if evt.TenantID != uuid.Nil {
		return evt.TenantID
	}
	if id := parseUUID(str(evt.Payload, "tenant_id")); id != uuid.Nil {
		return id
	}
	if id := parseUUID(str(evt.Payload, "id")); id != uuid.Nil {
		return id
	}
	return uuid.Nil
}

func str(m map[string]any, k string) string {
	if m == nil {
		return ""
	}
	if v, ok := m[k].(string); ok {
		return v
	}
	return ""
}

func boolean(m map[string]any, k string) bool {
	if m == nil {
		return false
	}
	if v, ok := m[k].(bool); ok {
		return v
	}
	return false
}

func parseUUID(s string) uuid.UUID {
	id, err := uuid.Parse(strings.TrimSpace(s))
	if err != nil {
		return uuid.Nil
	}
	return id
}
