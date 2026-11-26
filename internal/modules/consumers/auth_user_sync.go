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

	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
)

// platformEmailDomain is the platform owner's email domain. A user on this domain holding a
// superuser/admin role is treated as the PLATFORM owner and is NOT projected into a tenant's
// employee roster (see IsPlatformAdmin). Kept minimal + documented per the projection design.
const platformEmailDomain = "codevertexafrica.com"

// AuthUserSyncConsumer consumes auth.user.created / auth.user.updated events and projects each
// auth-api user into the local Employee table (keyed on the auth user id) via
// employees.Service.UpsertFromAuthUser. Mirrors TenantSyncConsumer EXACTLY: durable consumer
// per subject on the shared `auth` JetStream stream, queue-group for multi-replica safety,
// IdempotencyStore dedupe, explicit ack with ack-wait + max-deliver.
type AuthUserSyncConsumer struct {
	log  *zap.Logger
	svc  *employees.Service
	idem *sharedevents.IdempotencyStore
	// Entitled reports whether the tenant's plan includes the erp service. Tenants outside it get
	// no employee projection. Nil lets every tenant through (local development).
	Entitled func(ctx context.Context, tenantID uuid.UUID) bool
	// Deactivated is called with the auth user id of a deactivated or suspended account.
	Deactivated func(ctx context.Context, authUserID string) error
}

// handleUserDeactivated takes away what ERP gave a person whose account was deactivated.
func (c *AuthUserSyncConsumer) handleUserDeactivated(ctx context.Context, evt *sharedevents.Event) error {
	authUserID := parseUUID(str(evt.Payload, "user_id"))
	if authUserID == uuid.Nil {
		authUserID = evt.AggregateID
	}
	if authUserID == uuid.Nil {
		return fmt.Errorf("auth.user.deactivated event missing user id")
	}
	if c.Deactivated == nil {
		return nil
	}
	return c.Deactivated(ctx, authUserID.String())
}

func NewAuthUserSyncConsumer(log *zap.Logger, svc *employees.Service, idem *sharedevents.IdempotencyStore) *AuthUserSyncConsumer {
	return &AuthUserSyncConsumer{
		log:  log.Named("consumers.auth_user_sync"),
		svc:  svc,
		idem: idem,
	}
}

// Start ensures the auth stream exists and registers durable subscriptions for the user events.
func (c *AuthUserSyncConsumer) Start(ctx context.Context, nc *nats.Conn) error {
	if nc == nil {
		c.log.Warn("NATS not available; auth-user-sync consumers disabled")
		return nil
	}
	js, err := nc.JetStream()
	if err != nil {
		return fmt.Errorf("auth-user-sync: jetstream init: %w", err)
	}

	// Guard against a startup race with auth-api: ensure the auth stream exists.
	ensureStream(c.log, js, authStream)
	subscribeAll(ctx, c.log, js, authStream, c.idem, []subSpec{
		{"auth.user.created", "erp-auth-user-created", c.handleUserEvent},
		{"auth.user.updated", "erp-auth-user-updated", c.handleUserEvent},
		{"auth.user.deleted", "erp-auth-user-deleted", c.handleUserDeleted},
		{"auth.user.deactivated", "erp-auth-user-deactivated", c.handleUserDeactivated},
	})
	return nil
}

// handleUserEvent projects one auth.user.{created,updated} event into an Employee. Payload
// field names mirror auth-api's user-event publisher (auth/service.go publishEvent +
// admin_handler UpdateTenantMember): user_id, email, full_name, tenant_id, tenant_slug,
// roles[], outlet_id (optional). The `updated` event may omit email/full_name — the upsert
// only overwrites non-empty fields, so partial events are safe.
func (c *AuthUserSyncConsumer) handleUserEvent(ctx context.Context, evt *sharedevents.Event) error {
	tenantID := tenantIDFromEvent(evt)
	if tenantID == uuid.Nil {
		return fmt.Errorf("auth.user event missing tenant id")
	}
	if c.Entitled != nil && !c.Entitled(ctx, tenantID) {
		return nil // not in the erp plan: no CustomUser or Employee is created
	}
	authUserID := parseUUID(str(evt.Payload, "user_id"))
	if authUserID == uuid.Nil {
		// Fall back to the aggregate id (publishEvent sets AggregateID = user id).
		authUserID = evt.AggregateID
	}
	if authUserID == uuid.Nil {
		return fmt.Errorf("auth.user event missing user id")
	}

	email := str(evt.Payload, "email")
	fullName := str(evt.Payload, "full_name")
	if fullName == "" {
		fullName = str(evt.Payload, "name")
	}

	var outletID *uuid.UUID
	if oid := parseUUID(str(evt.Payload, "outlet_id")); oid != uuid.Nil {
		outletID = &oid
	}

	isPlatformAdmin := IsPlatformAdmin(email, rolesFromEvent(evt))

	if _, err := c.svc.UpsertFromAuthUser(ctx, tenantID, authUserID, email, fullName, outletID, isPlatformAdmin); err != nil {
		return err
	}
	c.log.Info("employee projected from auth user",
		zap.String("tenant_id", tenantID.String()),
		zap.String("auth_user_id", authUserID.String()),
		zap.String("event", evt.EventType),
		zap.Bool("skipped_platform_admin", isPlatformAdmin))
	return nil
}

// handleUserDeleted reacts to auth-api's real hard-delete (AdminPurgeUser) of a platform
// user by delegating to employees.Service.HardDeleteAuthUser — see that method's doc
// comment for the CustomUser-hard-delete-vs-Employee-soft-delete distinction.
func (c *AuthUserSyncConsumer) handleUserDeleted(ctx context.Context, evt *sharedevents.Event) error {
	authUserID := parseUUID(str(evt.Payload, "user_id"))
	if authUserID == uuid.Nil {
		authUserID = evt.AggregateID
	}
	if authUserID == uuid.Nil {
		return fmt.Errorf("auth.user.deleted event missing user id")
	}
	if err := c.svc.HardDeleteAuthUser(ctx, authUserID); err != nil {
		return err
	}
	c.log.Info("user hard-deleted from auth.user.deleted event", zap.String("auth_user_id", authUserID.String()))
	return nil
}

// handleUserDeactivated reacts to auth-api deactivating, suspending or setting a user inactive:
// the user's ERP login shadow is marked inactive and their employee records are flagged "login
// disabled, review exit" on the HR dashboard. Employment is an HR decision, so the employee
// record, its pay and its history are left as they are (HR exits a leaver with Mark as exited).
func (c *AuthUserSyncConsumer) handleUserDeactivated(ctx context.Context, evt *sharedevents.Event) error {
	authUserID := parseUUID(str(evt.Payload, "user_id"))
	if authUserID == uuid.Nil {
		authUserID = evt.AggregateID
	}
	if authUserID == uuid.Nil {
		return fmt.Errorf("auth.user.deactivated event missing user id")
	}
	at := evt.Timestamp
	if at.IsZero() {
		at = time.Now()
	}
	status := str(evt.Payload, "status")
	if status == "" {
		status = "deactivated"
	}
	flagged, err := c.svc.DeactivateAuthUser(ctx, authUserID, status, at)
	if err != nil {
		return err
	}
	c.log.Info("auth user deactivated", zap.String("auth_user_id", authUserID.String()),
		zap.String("status", status), zap.Int("employees_flagged", flagged))
	return nil
}

// IsPlatformAdmin is the minimal, documented guard that prevents the PLATFORM owner/superuser
// from being projected into a tenant's employee roster: true when the email is on the platform
// domain AND the user holds a superuser/admin role. Exported for reuse by the backfill command.
func IsPlatformAdmin(email string, roles []string) bool {
	email = strings.ToLower(strings.TrimSpace(email))
	if !strings.HasSuffix(email, "@"+platformEmailDomain) {
		return false
	}
	for _, r := range roles {
		switch strings.ToLower(strings.TrimSpace(r)) {
		case "superuser", "admin", "superusers":
			return true
		}
	}
	return false
}

// rolesFromEvent extracts the roles[] array from an event payload (values may be any).
func rolesFromEvent(evt *sharedevents.Event) []string {
	if evt == nil || evt.Payload == nil {
		return nil
	}
	raw, ok := evt.Payload["roles"].([]any)
	if !ok {
		return nil
	}
	out := make([]string, 0, len(raw))
	for _, v := range raw {
		if s, ok := v.(string); ok {
			out = append(out, s)
		}
	}
	return out
}
