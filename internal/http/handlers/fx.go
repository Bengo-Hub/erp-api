package handlers

import (
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/fx"
)

const (
	permFxView   = "fx.view"
	permFxManage = "fx.manage"
)

// FXHandler serves /api/v1/fx/* â€” stored exchange rates + an on-demand refresh.
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
	rows, err := h.svc.ListRates(r.Context(), scope.TenantID, r.URL.Query().Get("base"))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list rates")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

func (h *FXHandler) Refresh(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	// Refresh mutates stored rates (external fetch) — gate on manage, not view.
	if !ok || !requirePermission(w, scope, permFxManage) {
		return
	}
	// A company refreshes with its own settings; every company's only for the platform owner (the
	// scheduled job runs them all).
	var n int
	var err error
	if r.URL.Query().Get("scope") == "all" && isPlatformOwner(scope) {
		n, err = h.svc.FetchAllActive(r.Context())
	} else {
		n, err = h.svc.FetchForTenant(r.Context(), scope.TenantID)
	}
	if err != nil {
		writeError(w, http.StatusBadGateway, "fetch_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"rates_updated": n})
}
