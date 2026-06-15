package adapters

import "github.com/Bengo-Hub/erp-api/internal/modules/docs"

// withBranding applies the optional tenant branding fields to a freshly-built Document
// and returns it, so adapters can wrap their literal in one call.
func withBranding(d *docs.Document, ti TenantInfo) *docs.Document {
	ti.ApplyBranding(d)
	return d
}

// BrandingData is the subset of auth-api tenant branding the ERP documents consume. It
// mirrors platform/auth.Branding without importing it, keeping the adapters package free
// of the HTTP client. Handlers map the fetched branding into this and call FromBranding.
type BrandingData struct {
	Name         string
	Slug         string
	LogoURL      string
	PrimaryColor string
	KraPin       string
	Address      string
}

// FromBranding builds a TenantInfo from resolved auth-api branding + the tenant slug.
// branding may be nil (tenant not found / branding unavailable) — the document then
// renders with the slug as the only identity and the default palette.
func FromBranding(slug string, branding *BrandingData) TenantInfo {
	ti := TenantInfo{Slug: slug, Name: slug}
	if branding == nil {
		return ti
	}
	if branding.Slug != "" {
		ti.Slug = branding.Slug
	}
	if branding.Name != "" {
		ti.Name = branding.Name
	}
	ti.LogoURL = branding.LogoURL
	ti.PrimaryColor = branding.PrimaryColor
	ti.Address = branding.Address
	ti.TaxPIN = branding.KraPin
	return ti
}
