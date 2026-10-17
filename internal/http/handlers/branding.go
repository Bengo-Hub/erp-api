package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"go.uber.org/zap"

	platformauth "github.com/Bengo-Hub/erp-api/internal/platform/auth"
)

// BrandingHandler serves public branding for the login page (no auth). auth-api is the SoT
// for branding; this is a Redis-cached read-through of GET /api/v1/tenants/by-slug/{slug}
//. When the client is unconfigured it degrades to echoing the slug so the
// public route contract still holds and the login page renders.
type BrandingHandler struct {
	log    *zap.Logger
	client *platformauth.BrandingClient
}

func NewBrandingHandler(log *zap.Logger, client *platformauth.BrandingClient) *BrandingHandler {
	return &BrandingHandler{log: log.Named("branding.Handler"), client: client}
}

// PublicBranding handles GET /api/v1/business/public-branding/?slug=...
func (h *BrandingHandler) PublicBranding(w http.ResponseWriter, r *http.Request) {
	slug := r.URL.Query().Get("slug")
	if h.client != nil {
		if b, err := h.client.GetBySlug(r.Context(), slug); err == nil && b != nil {
			respondJSON(w, http.StatusOK, b)
			return
		} else if err != nil {
			h.log.Warn("branding read-through failed; degrading", zap.Error(err), zap.String("slug", slug))
		}
	}
	respondJSON(w, http.StatusOK, platformauth.Branding{Slug: slug})
}

// RegisterRoutes mounts the public branding route.
func (h *BrandingHandler) RegisterRoutes(r chi.Router) {
	r.Get("/business/public-branding/", h.PublicBranding)
	r.Get("/business/public-branding", h.PublicBranding)
}
