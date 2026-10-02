// Package subscriptions provides a per-feature entitlement check for erp-api. It mirrors the
// pos-api consumer-gate contract: S2S GET /api/v1/tenants/{id}/subscription with the shared
// INTERNAL_SERVICE_KEY, a short in-process TTL cache, exempt demo/service_charge tenants, and
// FAIL-OPEN on any lookup error (never block a paying tenant because the pricing API blipped).
package subscriptions

import (
	"context"
	"fmt"
	sharedcache "github.com/Bengo-Hub/cache"
	"strings"
	"time"

	serviceclient "github.com/Bengo-Hub/shared-service-client"
	"github.com/google/uuid"
	"go.uber.org/zap"
)

const entitlementCacheTTL = 60 * time.Second

// Entitlements is the canonical tenant subscription snapshot returned by subscriptions-api's
// GET /api/v1/tenants/{id}/subscription — the same full field set treasury-api's and pos-api's
// platform/subscriptions clients decode, so all fleet subscriptions clients converge on one
// shape instead of each reading a different partial subset (the "drifting shape" bug class
// behind the 2026-08-07 boi-enterprises subscription-gating audit).
type Entitlements struct {
	Features         []string       `json:"features"`
	Status           string         `json:"status"`
	BillingMode      string         `json:"billing_mode"`
	IsDemoBypass     bool           `json:"is_demo_bypass"`
	ActiveProducts   []string       `json:"active_products"`
	Limits           map[string]int `json:"limits"`
	PlanCode         string         `json:"plan_code"`
	TierOrder        int            `json:"tier_order"`
	AllowOverage     bool           `json:"allow_overage"`
	CurrentPeriodEnd string         `json:"current_period_end"`
	IsPerpetual      bool           `json:"is_perpetual"`
	Exempt           bool           `json:"exempt"`
}

// Client fetches + caches tenant entitlements over S2S, built on shared-service-client (circuit
// breaker + bounded retry) instead of a bare http.Client.
type Client struct {
	baseURL string
	apiKey  string
	sc      *serviceclient.Client
	log     *zap.Logger
	// cache is a bounded LRU with the entitlement TTL (the old map never dropped expired tenants).
	cache *sharedcache.Local[uuid.UUID, *Entitlements]
}

// NewClient builds a subscriptions gate client. A blank baseURL/apiKey disables it (HasFeature
// then fails open — allow). The retry budget is kept close to a single request's timeout (not
// shared-service-client's default 30s budget): this client sits on the S2S staff-purchase path,
// which must fail open fast on a subscriptions-api outage, not after a multi-second retry storm.
func NewClient(baseURL, apiKey string, log *zap.Logger) *Client {
	baseURL = strings.TrimRight(baseURL, "/")
	const timeout = 5 * time.Second
	scCfg := serviceclient.DefaultConfig(baseURL, "subscriptions-api", log)
	scCfg.Timeout = timeout
	scCfg.InitialInterval = 100 * time.Millisecond
	scCfg.MaxInterval = timeout
	scCfg.MaxElapsedTime = timeout
	return &Client{
		baseURL: baseURL,
		apiKey:  apiKey,
		sc:      serviceclient.New(scCfg),
		log:     log.Named("subscriptions.gate"),
		cache:   sharedcache.NewLocal[uuid.UUID, *Entitlements](4096, entitlementCacheTTL),
	}
}

// Enabled reports whether the client can make S2S calls.
func (c *Client) Enabled() bool { return c != nil && c.baseURL != "" && c.apiKey != "" }

// HasFeature reports whether tenant T is entitled to feature code F. Exempt (demo/service_charge)
// tenants always pass; any error or disabled client FAILS OPEN (returns true) so gating never
// hard-blocks a paying tenant on a transient pricing-API failure.
func (c *Client) HasFeature(ctx context.Context, tenantID uuid.UUID, code string) bool {
	if !c.Enabled() || tenantID == uuid.Nil {
		return true
	}
	ent, err := c.getEntitlements(ctx, tenantID)
	if err != nil || ent == nil {
		return true // fail open
	}
	if ent.IsDemoBypass || strings.EqualFold(ent.BillingMode, "service_charge") {
		return true
	}
	for _, f := range ent.Features {
		if f == code {
			return true
		}
	}
	return false
}

func (c *Client) getEntitlements(ctx context.Context, tenantID uuid.UUID) (*Entitlements, error) {
	if e, ok := c.cache.Get(tenantID); ok {
		return e, nil
	}

	headers := map[string]string{"X-API-Key": c.apiKey, "X-Tenant-ID": tenantID.String()}
	resp, err := c.sc.Get(ctx, fmt.Sprintf("/api/v1/tenants/%s/subscription", tenantID.String()), headers)
	if err != nil {
		c.log.Warn("entitlement lookup failed (fail-open)", zap.Error(err))
		return nil, err
	}
	if resp.StatusCode != 200 {
		return nil, fmt.Errorf("entitlement lookup: status %d", resp.StatusCode)
	}
	var ent Entitlements
	if err := resp.DecodeJSON(&ent); err != nil {
		return nil, err
	}
	c.cache.Set(tenantID, &ent)
	return &ent, nil
}
