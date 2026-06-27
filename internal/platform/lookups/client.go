// Package lookups is a thin cross-service read client for cost-allocation reference data the
// payroll component forms need: PROJECTS (owned by projects-api) and COST-CENTERS (owned by
// treasury-api). Per feedback_service_data_ownership the ERP never stores these masters — it
// reads them live over S2S.
//
// Auth: neither projects-api's GET /api/v1/{tenant}/projects nor treasury-api's
// GET /api/v1/{tenant}/cost-centers expose a dedicated X-API-Key S2S route (audited
// 2026-06-27) — both are JWT + RBAC gated. So this client FORWARDS the caller's own Bearer
// JWT (the user is already authenticated + tenant-scoped) and additionally sends the shared
// INTERNAL_SERVICE_KEY as X-API-Key for defense-in-depth. Responses are cached briefly.
//
// IMPORTANT (no-fabricated-paths rule, ref reference_kra_etims_gavaconnect): the two paths
// above are the REAL list endpoints confirmed in projects-api/treasury-api source. When a
// base URL is not configured or the upstream call fails, the handler falls back to distinct
// values already present on existing ERP records instead of inventing an endpoint.
package lookups

import (
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"strings"
	"sync"
	"time"

	"github.com/google/uuid"
	"go.uber.org/zap"
)

// Option is a normalized {value,label} lookup row the UI combobox consumes.
type Option struct {
	Value string `json:"value"`
	Label string `json:"label"`
}

// Client fetches projects + cost-centers from their owning services, forwarding the caller JWT.
type Client struct {
	projectsURL string
	treasuryURL string
	apiKey      string
	httpc       *http.Client
	log         *zap.Logger

	mu    sync.Mutex
	cache map[string]cacheEntry
	ttl   time.Duration
}

type cacheEntry struct {
	opts []Option
	exp  time.Time
}

// NewClient builds the lookups client. Empty base URLs disable the corresponding lookup
// (Projects/CostCenters return ErrUnavailable so the caller can fall back to ERP-derived values).
func NewClient(projectsURL, treasuryURL, apiKey string, log *zap.Logger) *Client {
	return &Client{
		projectsURL: strings.TrimRight(projectsURL, "/"),
		treasuryURL: strings.TrimRight(treasuryURL, "/"),
		apiKey:      apiKey,
		httpc:       &http.Client{Timeout: 8 * time.Second},
		log:         log.Named("lookups.client"),
		cache:       map[string]cacheEntry{},
		ttl:         60 * time.Second,
	}
}

// ErrUnavailable signals the upstream service is not configured (caller should fall back).
var ErrUnavailable = fmt.Errorf("lookups: upstream service not configured")

// ProjectsEnabled reports whether the projects-service base URL is configured.
func (c *Client) ProjectsEnabled() bool { return c.projectsURL != "" }

// CostCentersEnabled reports whether the treasury base URL is configured.
func (c *Client) CostCentersEnabled() bool { return c.treasuryURL != "" }

// Projects returns the tenant's projects from projects-api (GET /api/v1/{tenant}/projects),
// normalized to {value:id,label:name}. bearer is the caller's raw JWT (without the "Bearer "
// prefix) forwarded for auth.
func (c *Client) Projects(ctx context.Context, tenantID uuid.UUID, bearer string) ([]Option, error) {
	if c.projectsURL == "" {
		return nil, ErrUnavailable
	}
	key := "proj:" + tenantID.String()
	if v, ok := c.cached(key); ok {
		return v, nil
	}
	url := fmt.Sprintf("%s/api/v1/%s/projects?limit=500", c.projectsURL, tenantID.String())
	raw, err := c.get(ctx, url, bearer)
	if err != nil {
		return nil, err
	}
	opts := normalize(raw, "name")
	c.store(key, opts)
	return opts, nil
}

// CostCenters returns the tenant's cost-centers from treasury-api
// (GET /api/v1/{tenant}/cost-centers?active_only=true), normalized to {value:id,label:name (code)}.
func (c *Client) CostCenters(ctx context.Context, tenantID uuid.UUID, bearer string) ([]Option, error) {
	if c.treasuryURL == "" {
		return nil, ErrUnavailable
	}
	key := "cc:" + tenantID.String()
	if v, ok := c.cached(key); ok {
		return v, nil
	}
	url := fmt.Sprintf("%s/api/v1/%s/cost-centers?active_only=true", c.treasuryURL, tenantID.String())
	raw, err := c.get(ctx, url, bearer)
	if err != nil {
		return nil, err
	}
	opts := normalizeCostCenters(raw)
	c.store(key, opts)
	return opts, nil
}

func (c *Client) get(ctx context.Context, url, bearer string) (json.RawMessage, error) {
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	if bearer != "" {
		req.Header.Set("Authorization", "Bearer "+bearer)
	}
	if c.apiKey != "" {
		req.Header.Set("X-API-Key", c.apiKey)
	}
	resp, err := c.httpc.Do(req)
	if err != nil {
		return nil, fmt.Errorf("lookups: GET %s: %w", url, err)
	}
	defer func() { _ = resp.Body.Close() }()
	body, _ := io.ReadAll(io.LimitReader(resp.Body, 4<<20))
	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("lookups: GET %s: status %d", url, resp.StatusCode)
	}
	return json.RawMessage(body), nil
}

// listEnvelope tolerates the common response shapes: {data:[...]}, {results:[...]},
// {cost_centers:[...]} or a bare [...] array.
type listEnvelope struct {
	Data        []map[string]any `json:"data"`
	Results     []map[string]any `json:"results"`
	CostCenters []map[string]any `json:"cost_centers"`
}

func extractRows(raw json.RawMessage) []map[string]any {
	var env listEnvelope
	if err := json.Unmarshal(raw, &env); err == nil {
		switch {
		case len(env.Data) > 0:
			return env.Data
		case len(env.Results) > 0:
			return env.Results
		case len(env.CostCenters) > 0:
			return env.CostCenters
		}
	}
	var arr []map[string]any
	if err := json.Unmarshal(raw, &arr); err == nil {
		return arr
	}
	return nil
}

func normalize(raw json.RawMessage, labelKey string) []Option {
	rows := extractRows(raw)
	out := make([]Option, 0, len(rows))
	for _, r := range rows {
		id := strVal(r["id"])
		if id == "" {
			continue
		}
		label := strVal(r[labelKey])
		if label == "" {
			label = id
		}
		out = append(out, Option{Value: id, Label: label})
	}
	return out
}

func normalizeCostCenters(raw json.RawMessage) []Option {
	rows := extractRows(raw)
	out := make([]Option, 0, len(rows))
	for _, r := range rows {
		id := strVal(r["id"])
		if id == "" {
			continue
		}
		name := strVal(r["name"])
		code := strVal(r["code"])
		label := name
		if label == "" {
			label = id
		}
		if code != "" {
			label = fmt.Sprintf("%s (%s)", label, code)
		}
		out = append(out, Option{Value: id, Label: label})
	}
	return out
}

func strVal(v any) string {
	if v == nil {
		return ""
	}
	if s, ok := v.(string); ok {
		return s
	}
	return fmt.Sprintf("%v", v)
}

func (c *Client) cached(key string) ([]Option, bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	e, ok := c.cache[key]
	if !ok || time.Now().After(e.exp) {
		return nil, false
	}
	return e.opts, true
}

func (c *Client) store(key string, opts []Option) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.cache[key] = cacheEntry{opts: opts, exp: time.Now().Add(c.ttl)}
}
