package docs

import (
	"io"
	"net/http"
)

// GeneratePDF returns a premium, tenant-branded PDF document as bytes for the given
// Document. The tenant logo (if any) is fetched once and embedded; all rendering is
// delegated to the modular fpdf engine in render*.go.
func GeneratePDF(doc *Document) ([]byte, error) {
	logo, logoType := fetchLogoBytes(doc.TenantLogoURL)
	return renderPDF(doc, logo, logoType)
}

// fetchLogoBytes downloads the tenant logo from a URL and reports its fpdf image type
// ("PNG"/"JPG"/"GIF"). Returns nil bytes on any failure (graceful degradation — the
// document simply renders without a logo).
func fetchLogoBytes(logoURL string) ([]byte, string) {
	if logoURL == "" {
		return nil, ""
	}
	resp, err := http.Get(logoURL) //nolint:gosec // URL from trusted auth-api branding
	if err != nil {
		return nil, ""
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		return nil, ""
	}
	b, err := io.ReadAll(resp.Body)
	if err != nil || len(b) == 0 {
		return nil, ""
	}
	return b, imgType(b)
}
