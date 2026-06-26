package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/recruitment"
)

// CareersHandler serves the PUBLIC (unauthenticated) careers portal: a tenant's open job postings
// and public application submission. Tenant is resolved from the {slug} path segment (org slug).
type CareersHandler struct {
	log *zap.Logger
	svc *recruitment.Service
}

func NewCareersHandler(log *zap.Logger, svc *recruitment.Service) *CareersHandler {
	return &CareersHandler{log: log.Named("careers"), svc: svc}
}

// RegisterRoutes mounts the public careers routes. applyLimiter is applied to the (write) apply
// endpoint only; the read endpoints are cheap and cacheable.
func (h *CareersHandler) RegisterRoutes(r chi.Router, applyLimiter func(http.Handler) http.Handler) {
	r.Route("/careers/{slug}", func(cr chi.Router) {
		cr.Get("/postings", h.ListPostings)
		cr.Get("/postings/{postingSlug}", h.GetPosting)
		cr.With(applyLimiter).Post("/postings/{postingSlug}/applications", h.Apply)
	})
}

// publicPostingView exposes only the fields safe for an unauthenticated visitor.
func publicPostingView(p *ent.JobPosting) map[string]any {
	v := map[string]any{
		"slug":          p.Slug,
		"title":         p.Title,
		"description":   p.Description,
		"num_positions": p.NumPositions,
		"posted_at":     p.PostedAt.Format("2006-01-02"),
	}
	if p.Department != nil {
		v["department"] = *p.Department
	}
	if p.Location != nil {
		v["location"] = *p.Location
	}
	if p.EmploymentType != nil {
		v["employment_type"] = *p.EmploymentType
	}
	if p.ApplicationDeadline != nil {
		v["application_deadline"] = p.ApplicationDeadline.Format("2006-01-02")
	}
	return v
}

func (h *CareersHandler) tenant(w http.ResponseWriter, r *http.Request) (string, bool) {
	slug := chi.URLParam(r, "slug")
	if slug == "" {
		writeError(w, http.StatusBadRequest, "bad_request", "missing organization slug")
		return "", false
	}
	return slug, true
}

// ListPostings returns a tenant's public, open job postings.
func (h *CareersHandler) ListPostings(w http.ResponseWriter, r *http.Request) {
	slug, ok := h.tenant(w, r)
	if !ok {
		return
	}
	tenantID, err := h.svc.TenantBySlug(r.Context(), slug)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "organization not found")
		return
	}
	rows, err := h.svc.PublicPostings(r.Context(), tenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load postings")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, p := range rows {
		out = append(out, publicPostingView(p))
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": out, "count": len(out)})
}

// GetPosting returns one public posting by slug.
func (h *CareersHandler) GetPosting(w http.ResponseWriter, r *http.Request) {
	slug, ok := h.tenant(w, r)
	if !ok {
		return
	}
	tenantID, err := h.svc.TenantBySlug(r.Context(), slug)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "organization not found")
		return
	}
	p, err := h.svc.PublicPostingBySlug(r.Context(), tenantID, chi.URLParam(r, "postingSlug"))
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "posting not found")
		return
	}
	writeJSON(w, http.StatusOK, publicPostingView(p))
}

type applyBody struct {
	FullName    string `json:"full_name"`
	Email       string `json:"email"`
	Phone       string `json:"phone"`
	CoverLetter string `json:"cover_letter"`
	ResumeURL   string `json:"resume_url"`
}

// Apply records a public job application for the posting slug.
func (h *CareersHandler) Apply(w http.ResponseWriter, r *http.Request) {
	slug, ok := h.tenant(w, r)
	if !ok {
		return
	}
	tenantID, err := h.svc.TenantBySlug(r.Context(), slug)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "organization not found")
		return
	}
	var b applyBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	app, err := h.svc.PublicApply(r.Context(), tenantID, recruitment.PublicApplyInput{
		PostingSlug: chi.URLParam(r, "postingSlug"),
		FullName:    b.FullName,
		Email:       b.Email,
		Phone:       b.Phone,
		CoverLetter: b.CoverLetter,
		ResumeURL:   b.ResumeURL,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "apply_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"id": app.ID, "status": "received"})
}
