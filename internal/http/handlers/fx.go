package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/fx"
)

const permFxView = "fx.view"

// FXHandler serves /api/v1/fx/* — stored exchange rates + an on-demand refresh.
type FXHandler struct {
	log *zap.Logger
	svc *fx.Service
}

func NewFXHandler(log *zap.Logger, svc *fx.Service) *FXHandler {
	return &FXHandler{log: log.Named("fx"), svc: svc}
}

func (h *FXHandler) RegisterRoutes(r chi.Router) {
	r.Route("/fx", func(fr chi.Router) {
		fr.Get("/rates", h.ListRates)
		fr.Post("/refresh", h.Refresh)
	})
}

func (h *FXHandler) ListRates(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permFxView) {
		return
	}
	rows, err := h.svc.ListRates(r.Context(), r.URL.Query().Get("base"))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list rates")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}

func (h *FXHandler) Refresh(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permFxView) {
		return
	}
	n, err := h.svc.FetchAllActive(r.Context())
	if err != nil {
		writeError(w, http.StatusBadGateway, "fetch_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"rates_updated": n})
}
