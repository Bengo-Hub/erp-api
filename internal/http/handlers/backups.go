package handlers

import (
	"fmt"
	"io"
	"net/http"

	"github.com/go-chi/chi/v5"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/backup"
)

// Backup RBAC permission codes (sensitive — admin-scoped).
const (
	permBackupsView   = "backups.view"
	permBackupsManage = "backups.manage"
)

// BackupsHandler serves /api/v1/backups — TENANT-SCOPED backups (this tenant's data
// only). Replaces the old platform-wide DB-dump listing. Platform owners operate on
// their resolved tenant (the ?tenantId= override scopes the whole request).
type BackupsHandler struct {
	log *zap.Logger
	svc *backup.Service
}

func NewBackupsHandler(log *zap.Logger, svc *backup.Service) *BackupsHandler {
	return &BackupsHandler{log: log.Named("backups.Handler"), svc: svc}
}

func (h *BackupsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/backups", func(br chi.Router) {
		br.Get("/", h.List)
		br.Post("/", h.Create)
		br.Get("/{name}/download", h.Download)
		br.Delete("/{name}", h.Delete)
	})
}

func (h *BackupsHandler) List(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsView) {
		return
	}
	items, err := h.svc.List(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list backups")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"backups": items})
}

func (h *BackupsHandler) Create(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsManage) {
		return
	}
	info, err := h.svc.Generate(r.Context(), scope.TenantID)
	if err != nil {
		h.log.Error("generate backup", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "backup_failed", "failed to generate backup")
		return
	}
	writeJSON(w, http.StatusCreated, info)
}

func (h *BackupsHandler) Download(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsView) {
		return
	}
	name := chi.URLParam(r, "name")
	rc, err := h.svc.Open(scope.TenantID, name)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "backup not found")
		return
	}
	defer func() { _ = rc.Close() }()
	w.Header().Set("Content-Type", "application/gzip")
	w.Header().Set("Content-Disposition", fmt.Sprintf(`attachment; filename=%q`, name))
	w.Header().Set("Cache-Control", "no-store")
	w.WriteHeader(http.StatusOK)
	_, _ = io.Copy(w, rc)
}

func (h *BackupsHandler) Delete(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsManage) {
		return
	}
	if err := h.svc.Delete(scope.TenantID, chi.URLParam(r, "name")); err != nil {
		writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
