package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"go.uber.org/zap"
)

// BrandingHandler serves public branding for the login page (no auth).
// auth-api is the source of truth for branding; this is a read-through cache surface.
//
// TODO(sprint-2): wire the auth-api S2S GET /api/v1/tenants/by-slug/{slug} read-through
// (Redis-cached 6h, per docs/integrations.md §8). For now it returns an empty 200 so the
// public route contract exists and the login page degrades gracefully.
type BrandingHandler struct {
	log *zap.Logger
}

func NewBrandingHandler(log *zap.Logger) *BrandingHandler {
	return &BrandingHandler{log: log.Named("branding.Handler")}
}

type brandingResponse struct {
	Name           string `json:"name"`
	Slug           string `json:"slug"`
	LogoURL        string `json:"logo_url"`
	PrimaryColor   string `json:"primary_color"`
	SecondaryColor string `json:"secondary_color"`
	KraPin         string `json:"kra_pin"`
	Address        string `json:"address"`
}

// PublicBranding handles GET /api/v1/business/public-branding/.
func (h *BrandingHandler) PublicBranding(w http.ResponseWriter, r *http.Request) {
	slug := r.URL.Query().Get("slug")
	respondJSON(w, http.StatusOK, brandingResponse{Slug: slug})
}

// RegisterRoutes mounts the public branding route.
func (h *BrandingHandler) RegisterRoutes(r chi.Router) {
	r.Get("/business/public-branding/", h.PublicBranding)
	r.Get("/business/public-branding", h.PublicBranding)
}
