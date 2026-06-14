// Package auth is a service-to-service client for auth-api. auth-api is the SoT for tenant
// identity + branding; erp-api only READS branding through this Redis-cached read-through
// (GET /api/v1/tenants/by-slug/{slug}, public per integrations.md / plan §0a-map). erp-api
// never owns or mutates branding.
package auth

import (
	"context"
	"encoding/json"
	"fmt"
	"net/http"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

// Branding is the subset of the auth-api tenant payload the ERP surfaces (login page +
// PDF/report headers). Unknown fields are ignored.
type Branding struct {
	Name           string `json:"name"`
	Slug           string `json:"slug"`
	LogoURL        string `json:"logo_url"`
	PrimaryColor   string `json:"primary_color"`
	SecondaryColor string `json:"secondary_color"`
	KraPin         string `json:"kra_pin"`
	Address        string `json:"address"`
}

// BrandingClient fetches tenant branding from auth-api with a Redis read-through cache.
type BrandingClient struct {
	baseURL string
	http    *http.Client
	redis   *redis.Client
	ttl     time.Duration
	log     *zap.Logger
}

// NewBrandingClient builds the read-through branding client. redis may be nil (cache off).
func NewBrandingClient(baseURL string, redis *redis.Client, log *zap.Logger) *BrandingClient {
	return &BrandingClient{
		baseURL: strings.TrimRight(baseURL, "/"),
		http:    &http.Client{Timeout: 8 * time.Second},
		redis:   redis,
		ttl:     6 * time.Hour,
		log:     log.Named("auth.branding"),
	}
}

func cacheKey(slug string) string { return "erp:branding:" + slug }

// GetBySlug returns branding for a tenant slug, serving from Redis when warm and falling
// back to the auth-api public endpoint (then caching). Returns (nil, nil) when not found.
func (c *BrandingClient) GetBySlug(ctx context.Context, slug string) (*Branding, error) {
	if slug == "" {
		return nil, nil
	}
	if c.redis != nil {
		if raw, err := c.redis.Get(ctx, cacheKey(slug)).Result(); err == nil && raw != "" {
			var b Branding
			if json.Unmarshal([]byte(raw), &b) == nil {
				return &b, nil
			}
		}
	}
	if c.baseURL == "" {
		return nil, nil
	}
	url := fmt.Sprintf("%s/api/v1/tenants/by-slug/%s", c.baseURL, slug)
	req, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
	if err != nil {
		return nil, err
	}
	resp, err := c.http.Do(req)
	if err != nil {
		return nil, fmt.Errorf("auth branding: fetch: %w", err)
	}
	defer resp.Body.Close()
	if resp.StatusCode == http.StatusNotFound {
		return nil, nil
	}
	if resp.StatusCode >= 300 {
		return nil, fmt.Errorf("auth branding: status %d", resp.StatusCode)
	}
	var b Branding
	if err := json.NewDecoder(resp.Body).Decode(&b); err != nil {
		return nil, fmt.Errorf("auth branding: decode: %w", err)
	}
	if b.Slug == "" {
		b.Slug = slug
	}
	if c.redis != nil {
		if raw, err := json.Marshal(b); err == nil {
			_ = c.redis.Set(ctx, cacheKey(slug), raw, c.ttl).Err()
		}
	}
	return &b, nil
}
