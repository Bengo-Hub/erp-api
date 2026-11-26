package consumers

import (
	"context"
	"testing"

	sharedevents "github.com/Bengo-Hub/shared-events"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/services/usersync"
)

// A partial auth event never resets what the shadow already knows: a missing status, is_hq or
// is_platform keeps the stored value, an outlet event that carries its id only in the envelope
// still lands, and the founder notification subjects are not tenant updates.
func TestIntegration_AuthShadowPartialEvents(t *testing.T) {
	client := consumersTestClient(t)
	ctx := context.Background()
	c := &TenantSyncConsumer{log: zap.NewNop(), syncer: usersync.NewTenantSyncer(client, zap.NewNop())}
	tenant, outlet := uuid.New(), uuid.New()

	full := sharedevents.NewEvent("created", "auth", tenant, tenant, map[string]any{
		"tenant_id": tenant.String(), "slug": "acme", "name": "Acme", "status": "suspended", "is_platform": true,
	})
	if err := c.handleTenantEvent(ctx, full); err != nil {
		t.Fatal(err)
	}
	partial := sharedevents.NewEvent("updated", "auth", tenant, tenant, map[string]any{
		"tenant_id": tenant.String(), "name": "Acme Ltd",
	})
	if err := c.handleTenantEvent(ctx, partial); err != nil {
		t.Fatal(err)
	}
	notify := sharedevents.NewEvent("created.notify", "auth", tenant, tenant, map[string]any{
		"tenant_id": tenant.String(), "name": "Founder Person", "org_name": "Acme Ltd",
	})
	if err := c.handleTenantEvent(ctx, notify); err != nil {
		t.Fatal(err)
	}
	tn := client.AuthTenant.GetX(ctx, tenant)
	if tn.Status != "suspended" || !tn.IsPlatform || tn.Name != "Acme Ltd" || tn.Slug != "acme" {
		t.Errorf("tenant = %q %v %q %q, want suspended, platform, Acme Ltd, acme", tn.Status, tn.IsPlatform, tn.Name, tn.Slug)
	}

	created := sharedevents.NewEvent("created", "auth", outlet, tenant, map[string]any{
		"id": outlet.String(), "tenant_id": tenant.String(), "name": "HQ", "code": "HQ", "is_hq": true,
		"status": "inactive", "timezone": "Africa/Nairobi",
	})
	if err := c.handleOutletEvent(ctx, created); err != nil {
		t.Fatal(err)
	}
	// auth-api's eTIMS branch republish: outlet id only in the envelope, no name, status or is_hq.
	etims := sharedevents.NewEvent("updated", "auth", outlet, tenant, map[string]any{
		"metadata": map[string]any{"etims_branch_id": "01"}, "address": "Moi Avenue",
	})
	if err := c.handleOutletEvent(ctx, etims); err != nil {
		t.Fatalf("envelope-only outlet event: %v", err)
	}
	o := client.AuthOutlet.GetX(ctx, outlet)
	if !o.IsHq || o.Status != "inactive" || o.Name != "HQ" || o.Timezone != "Africa/Nairobi" {
		t.Errorf("outlet = hq %v %q %q %q, want hq, inactive, HQ, Africa/Nairobi", o.IsHq, o.Status, o.Name, o.Timezone)
	}

	// An envelope-only event for an outlet erp has never seen creates no nameless row.
	stranger := uuid.New()
	if err := c.handleOutletEvent(ctx, sharedevents.NewEvent("updated", "auth", stranger, tenant, map[string]any{"address": "x"})); err != nil {
		t.Fatal(err)
	}
	if client.AuthOutlet.Query().CountX(ctx) != 1 {
		t.Error("a nameless outlet shadow was created")
	}
}
