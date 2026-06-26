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

	sharedcache "github.com/Bengo-Hub/cache"
	"go.uber.org/zap"
)

// brandingTTL matches the JWT/tenant lifetime — branding rarely changes.
const brandingTTL = 6 * time.Hour

// Branding is the subset of the auth-api tenant payload the ERP surfaces (login page +
// careers portal + PDF/report headers). Unknown fields are ignored.
type Branding struct {
	Name           string `json:"name"`
	Slug           string `json:"slug"`
	LogoURL        string `json:"logo_url"`
	PrimaryColor   string `json:"primary_color"`
	SecondaryColor string `json:"secondary_color"`
	AccentColor    string `json:"accent_color"`
	KraPin         string `json:"kra_pin"`
	Address        string `json:"address"`
}

// rawTenant mirrors the auth-api by-slug payload shape: brand colours live under brand_colors
// and kra_pin/address under metadata (NOT as flat fields), so a flat decode yields empty
// colours. We also accept flat fields as a fallback for older payloads.
type rawTenant struct {
	Name        string `json:"name"`
	Slug        string `json:"slug"`
	LogoURL     string `json:"logo_url"`
	BrandColors struct {
		Primary   string `json:"primary"`
		Secondary string `json:"secondary"`
		Accent    string `json:"accent"`
	} `json:"brand_colors"`
	Metadata struct {
		KraPin  string `json:"kra_pin"`
		Address string `json:"address"`
	} `json:"metadata"`
	// Flat fallbacks.
	PrimaryColor   string `json:"primary_color"`
	SecondaryColor string `json:"secondary_color"`
	KraPin         string `json:"kra_pin"`
	Address        string `json:"address"`
}

func (r rawTenant) toBranding(slug string) *Branding {
	pick := func(a, b string) string {
		if a != "" {
			return a
		}
		return b
	}
	b := &Branding{
		Name:           r.Name,
		Slug:           pick(r.Slug, slug),
		LogoURL:        r.LogoURL,
		PrimaryColor:   pick(r.BrandColors.Primary, r.PrimaryColor),
		SecondaryColor: pick(r.BrandColors.Secondary, r.SecondaryColor),
		AccentColor:    r.BrandColors.Accent,
		KraPin:         pick(r.Metadata.KraPin, r.KraPin),
		Address:        pick(r.Metadata.Address, r.Address),
	}
	return b
}

// BrandingClient fetches tenant branding from auth-api with a shared cache-aside
// read-through (github.com/Bengo-Hub/cache). The cache may be nil (cache off).
type BrandingClient struct {
	baseURL string
	http    *http.Client
	cache   *sharedcache.Aside
	log     *zap.Logger
}

// NewBrandingClient builds the read-through branding client. cache may be nil (cache off).
func NewBrandingClient(baseURL string, cache *sharedcache.Aside, log *zap.Logger) *BrandingClient {
	return &BrandingClient{
		baseURL: strings.TrimRight(baseURL, "/"),
		http:    &http.Client{Timeout: 8 * time.Second},
		cache:   cache,
		log:     log.Named("auth.branding"),
	}
}

// GetBySlug returns branding for a tenant slug, serving from the shared cache when warm
// and falling back to the auth-api public endpoint (then caching). Returns (nil, nil)
// when not found.
func (c *BrandingClient) GetBySlug(ctx context.Context, slug string) (*Branding, error) {
	if slug == "" {
		return nil, nil
	}
	if c.cache != nil {
		// "branding2" busts entries cached under the old flat-decode (empty brand colours).
		key := sharedcache.Key("erp", "branding2", slug)
		b, err := sharedcache.GetOrSet(ctx, c.cache, key, brandingTTL, func(ctx context.Context) (*Branding, error) {
			return c.fetch(ctx, slug)
		})
		if err != nil {
			return nil, err
		}
		return b, nil
	}
	return c.fetch(ctx, slug)
}

// fetch reads branding directly from the auth-api public by-slug endpoint.
func (c *BrandingClient) fetch(ctx context.Context, slug string) (*Branding, error) {
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
	var raw rawTenant
	if err := json.NewDecoder(resp.Body).Decode(&raw); err != nil {
		return nil, fmt.Errorf("auth branding: decode: %w", err)
	}
	return raw.toBranding(slug), nil
}
