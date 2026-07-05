// Package subscriptions provides a minimal per-feature entitlement check for erp-api. ERP only had
// binary active-subscription gating; this adds "does tenant T have feature F", used to gate premium
// features (e.g. staff_fund_from_salary) on the S2S staff-purchase path where there is no user JWT.
//
// It mirrors the pos-api consumer-gate contract: S2S GET /api/v1/tenants/{id}/subscription with the
// shared INTERNAL_SERVICE_KEY, a short in-process TTL cache, exempt demo/service_charge tenants, and
// FAIL-OPEN on any lookup error (never block a paying tenant because the pricing API blipped).
package subscriptions

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"
)

const entitlementCacheTTL = 60 * time.Second

// Entitlements is the subset of GET /tenants/{id}/subscription this gate needs.
type Entitlements struct {
	Features     []string `json:"features"`
	Status       string   `json:"status"`
	BillingMode  string   `json:"billing_mode"`
	IsDemoBypass bool     `json:"is_demo_bypass"`
}

type cacheEntry struct {
	ent *Entitlements
	at  time.Time
}

// Client fetches + caches tenant entitlements.
type Client struct {
	baseURL string
	apiKey  string
	http    *http.Client
	log     *zap.Logger
	mu      sync.Mutex
	cache   map[uuid.UUID]cacheEntry
}

// NewClient builds a subscriptions gate client. A blank baseURL/apiKey disables it (HasFeature
// then fails open — allow).
func NewClient(baseURL, apiKey string, log *zap.Logger) *Client {
	return &Client{
		baseURL: strings.TrimRight(baseURL, "/"),
		apiKey:  apiKey,
		http:    &http.Client{Timeout: 5 * time.Second},
		log:     log.Named("subscriptions.gate"),
		cache:   map[uuid.UUID]cacheEntry{},
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
	c.mu.Lock()
	if e, ok := c.cache[tenantID]; ok && time.Since(e.at) < entitlementCacheTTL {
		c.mu.Unlock()
		return e.ent, nil
	}
	c.mu.Unlock()

	url := fmt.Sprintf("%s/api/v1/tenants/%s/subscription", c.baseURL, tenantID.String())
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	req.Header.Set("X-API-Key", c.apiKey)
	resp, err := c.http.Do(req)
	if err != nil {
		c.log.Warn("entitlement lookup failed (fail-open)", zap.Error(err))
		return nil, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("entitlement lookup: status %d", resp.StatusCode)
	}
	var ent Entitlements
	if err := json.NewDecoder(resp.Body).Decode(&ent); err != nil {
		return nil, err
	}
	c.mu.Lock()
	c.cache[tenantID] = cacheEntry{ent: &ent, at: time.Now()}
	c.mu.Unlock()
	return &ent, nil
}
