package handlers

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"

	"github.com/Bengo-Hub/pagination"
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
	log           *zap.Logger
	svc           *backup.Service
	retentionDays int
}

func NewBackupsHandler(log *zap.Logger, svc *backup.Service, retentionDays int) *BackupsHandler {
	if retentionDays <= 0 {
		retentionDays = backup.DefaultRetentionDays
	}
	return &BackupsHandler{log: log.Named("backups.Handler"), svc: svc, retentionDays: retentionDays}
}

func (h *BackupsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/backups", func(br chi.Router) {
		br.Get("/", h.List)
		br.Post("/", h.Create)
		br.Get("/settings", h.GetSettings)
		br.Put("/settings", h.UpdateSettings)
		br.Post("/churn", h.Churn)
		br.Get("/{name}/download", h.Download)
		br.Delete("/{name}", h.Delete)
	})
}

// GetSettings returns the tenant's auto-backup settings (auto_enabled defaults to false).
func (h *BackupsHandler) GetSettings(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsView) {
		return
	}
	settings, err := h.svc.GetSettings(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load backup settings")
		return
	}
	writeJSON(w, http.StatusOK, settings)
}

type backupSettingsBody struct {
	AutoEnabled   bool `json:"auto_enabled"`
	ScheduleHour  int  `json:"schedule_hour"`
	RetentionDays int  `json:"retention_days"`
}

// UpdateSettings activates/deactivates auto-backup + sets schedule hour + retention.
func (h *BackupsHandler) UpdateSettings(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsManage) {
		return
	}
	var b backupSettingsBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	settings, err := h.svc.UpsertSettings(r.Context(), scope.TenantID, backup.Settings{
		AutoEnabled: b.AutoEnabled, ScheduleHour: b.ScheduleHour, RetentionDays: b.RetentionDays,
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "save_failed", "failed to save backup settings")
		return
	}
	writeJSON(w, http.StatusOK, settings)
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
	writePagedSlice(w, items, pagination.Parse(r))
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

// Churn manually triggers retention cleanup (deletes files + tracking rows older than the
// configured retention window across the cluster). Admin/manage-gated. The daily scheduler
// runs this automatically; this endpoint is for on-demand pruning.
func (h *BackupsHandler) Churn(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsManage) {
		return
	}
	removed, err := h.svc.Churn(r.Context(), h.retentionDays)
	if err != nil {
		h.log.Error("churn backups", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "churn_failed", "failed to churn backups")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"removed": removed, "retention_days": h.retentionDays})
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
	if err := h.svc.Delete(r.Context(), scope.TenantID, chi.URLParam(r, "name")); err != nil {
		writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
