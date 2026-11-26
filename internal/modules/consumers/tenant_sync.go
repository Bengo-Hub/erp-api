package consumers

import (
	"context"
	"fmt"
	"strings"

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
// missing module import can never silently drop handlers, and redelivery
// is deduped.
type TenantSyncConsumer struct {
	log    *zap.Logger
	syncer *usersync.TenantSyncer
	idem   *sharedevents.IdempotencyStore
	// Entitled reports whether the tenant's plan includes the erp service. Tenants outside it get
	// no AuthTenant or AuthOutlet shadow. Nil lets every tenant through (local development).
	Entitled func(ctx context.Context, tenantID uuid.UUID) bool
}

func (c *TenantSyncConsumer) entitled(ctx context.Context, tenantID uuid.UUID) bool {
	return c.Entitled == nil || c.Entitled(ctx, tenantID)
}

func NewTenantSyncConsumer(log *zap.Logger, syncer *usersync.TenantSyncer, idem *sharedevents.IdempotencyStore) *TenantSyncConsumer {
	return &TenantSyncConsumer{
		log:    log.Named("consumers.tenant_sync"),
		syncer: syncer,
		idem:   idem,
	}
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
	ensureStream(c.log, js, authStream)
	subscribeAll(ctx, c.log, js, authStream, c.idem, []subSpec{
		{"auth.tenant.>", "erp-auth-tenant", c.handleTenantEvent},
		{"auth.outlet.>", "erp-auth-outlet", c.handleOutletEvent},
	})
	return nil
}

func (c *TenantSyncConsumer) handleTenantEvent(ctx context.Context, evt *sharedevents.Event) error {
	// auth.tenant.<type>.notify are founder emails (name is the founder's, not the company's).
	if evt.EventType == "notify" || strings.HasSuffix(evt.EventType, ".notify") {
		return nil
	}
	id := tenantIDFromEvent(evt)
	if id == uuid.Nil {
		return fmt.Errorf("auth.tenant event missing tenant id")
	}
	if !c.entitled(ctx, id) {
		return nil // not in the erp plan: no shadow row
	}
	in := usersync.TenantInput{
		ID:         id,
		Slug:       str(evt.Payload, "slug"),
		Name:       str(evt.Payload, "name"),
		Status:     str(evt.Payload, "status"),
		IsPlatform: optBool(evt.Payload, "is_platform"),
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
		// auth-api's outbox sets the aggregate id to the outlet (the eTIMS branch republish
		// carries it nowhere else).
		outletID = evt.AggregateID
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
	if !c.entitled(ctx, tenantID) {
		return nil // not in the erp plan: no outlet shadow
	}
	in := usersync.OutletInput{
		ID:       outletID,
		TenantID: tenantID,
		Code:     str(evt.Payload, "code"),
		Name:     str(evt.Payload, "name"),
		UseCase:  str(evt.Payload, "use_case"),
		IsHQ:     optBool(evt.Payload, "is_hq"),
		Status:   str(evt.Payload, "status"),
		Timezone: str(evt.Payload, "timezone"),
	}
	row, err := c.syncer.UpsertOutlet(ctx, in)
	if err != nil {
		return err
	}
	if row == nil {
		c.log.Info("outlet event for an unknown outlet without a name skipped", zap.String("outlet_id", outletID.String()))
		return nil
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

// optBool returns the payload boolean, or nil when the event does not carry it.
func optBool(m map[string]any, k string) *bool {
	if v, ok := m[k].(bool); ok {
		return &v
	}
	return nil
}

func parseUUID(s string) uuid.UUID {
	id, err := uuid.Parse(strings.TrimSpace(s))
	if err != nil {
		return uuid.Nil
	}
	return id
}
