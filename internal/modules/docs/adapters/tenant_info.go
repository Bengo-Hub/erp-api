package adapters

import "github.com/Bengo-Hub/erp-api/internal/modules/docs"

// TenantInfo carries all tenant branding and contact fields needed for document
// generation. Callers build this from auth-api branding (BrandingClient.GetBySlug).
type TenantInfo struct {
	Name         string
	Slug         string
	Email        string
	Phone        string
	Address      string // street / po-box line (optional)
	Country      string
	Website      string
	LogoURL      string
	PrimaryColor string // hex e.g. "#6366f1"; empty → default indigo
	BankDetails  *docs.BankDetails

	// Optional premium-template branding.
	Tagline    string // tagline shown under the company name
	TaxPIN     string // KRA / tax PIN
	PreparedBy string // default "Prepared By" signatory
	ApprovedBy string // default "Approved By" signatory
}

// ApplyBranding copies the optional tenant branding fields onto a Document. The core
// tenant fields (name, email, logo, colors) are set inline by each adapter; this fills
// the premium-template extras shared by all document types.
func (ti TenantInfo) ApplyBranding(d *docs.Document) {
	d.Tagline = ti.Tagline
	d.TaxPIN = ti.TaxPIN
	d.PreparedBy = ti.PreparedBy
	d.ApprovedBy = ti.ApprovedBy
}
