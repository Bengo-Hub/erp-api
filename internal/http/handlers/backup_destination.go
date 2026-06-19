package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/backup/destination"
)

// BackupDestinationHandler exposes platform-default and per-tenant management of
// the pluggable backup destination (OneDrive / Google Drive / S3 / WebDAV / SFTP
// / SMB) used to mirror tenant backups off the local PVC. Secret backend params
// are encrypted at rest (via the SECRET_KEY-derived cipher), masked in all
// responses, and never logged.
type BackupDestinationHandler struct {
	store    *destination.Store
	uploader *destination.Uploader
	log      *zap.Logger
}

// NewBackupDestinationHandler builds the handler over a destination Store +
// Uploader. The same Store instance is shared with the backup service's Mirrorer
// during app wiring so reads/writes and mirroring see one config source.
func NewBackupDestinationHandler(store *destination.Store, uploader *destination.Uploader, log *zap.Logger) *BackupDestinationHandler {
	return &BackupDestinationHandler{
		store:    store,
		uploader: uploader,
		log:      log.Named("backup-destination-handler"),
	}
}

// destinationResponse is the masked, API-safe view of a stored destination.
type destinationResponse struct {
	Configured bool                      `json:"configured"`
	Type       string                    `json:"type"`
	Enabled    bool                      `json:"enabled"`
	RemotePath string                    `json:"remote_path"`
	Params     []destination.MaskedParam `json:"params"`
}

type upsertDestinationRequest struct {
	Type       string            `json:"type"`
	Enabled    bool              `json:"enabled"`
	RemotePath string            `json:"remote_path"`
	Params     map[string]string `json:"params"`
}

// RegisterPlatformRoutes registers the platform-default destination routes. erp-api
// has no separate platform router, so these are gated INTERNALLY on IsPlatformOwner
// (the platform default is the tenant_id=NULL row).
func (h *BackupDestinationHandler) RegisterPlatformRoutes(r chi.Router) {
	r.Route("/platform/backups/destination", func(d chi.Router) {
		d.Get("/", h.GetPlatform)
		d.Put("/", h.PutPlatform)
		d.Post("/test", h.TestPlatform)
	})
}

// RegisterRoutes registers the per-tenant override destination routes alongside the
// existing /backups routes, gated on the same backups.view/backups.manage perms.
func (h *BackupDestinationHandler) RegisterRoutes(r chi.Router) {
	r.Route("/backups/destination", func(d chi.Router) {
		d.Get("/", h.GetTenant)
		d.Put("/", h.PutTenant)
		d.Post("/test", h.TestTenant)
	})
}

// --- platform (tenant_id NULL) ---

// GetPlatform returns the masked platform-default destination.
func (h *BackupDestinationHandler) GetPlatform(w http.ResponseWriter, r *http.Request) {
	if !h.requirePlatformOwner(w, r) {
		return
	}
	h.get(w, r, nil)
}

// PutPlatform validates and stores the platform-default destination.
func (h *BackupDestinationHandler) PutPlatform(w http.ResponseWriter, r *http.Request) {
	if !h.requirePlatformOwner(w, r) {
		return
	}
	h.put(w, r, nil)
}

// TestPlatform runs a connection test against the posted destination body.
func (h *BackupDestinationHandler) TestPlatform(w http.ResponseWriter, r *http.Request) {
	if !h.requirePlatformOwner(w, r) {
		return
	}
	h.test(w, r)
}

// requirePlatformOwner gates the platform-default endpoints on platform-owner
// identity (erp-api has no dedicated platform router). Writes 403 and returns false
// when the caller is not a platform owner.
func (h *BackupDestinationHandler) requirePlatformOwner(w http.ResponseWriter, r *http.Request) bool {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return false
	}
	if scope.Claims == nil || !scope.Claims.IsPlatformOwner {
		writeError(w, http.StatusForbidden, "forbidden", "platform owner required")
		return false
	}
	return true
}

// --- tenant override ---

// GetTenant returns the masked per-tenant destination override.
func (h *BackupDestinationHandler) GetTenant(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsView) {
		return
	}
	tenantID := scope.TenantID
	h.get(w, r, &tenantID)
}

// PutTenant validates and stores the per-tenant destination override.
func (h *BackupDestinationHandler) PutTenant(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsManage) {
		return
	}
	tenantID := scope.TenantID
	h.put(w, r, &tenantID)
}

// TestTenant runs a connection test against the posted destination body.
func (h *BackupDestinationHandler) TestTenant(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permBackupsManage) {
		return
	}
	h.test(w, r)
}

// --- shared impl ---

func (h *BackupDestinationHandler) get(w http.ResponseWriter, r *http.Request, tenantID *uuid.UUID) {
	d, found := h.store.Get(r.Context(), tenantID)
	if !found {
		// No row at this scope — report the inert default (PVC-only).
		d = destination.PVCOnly()
	}
	writeJSON(w, http.StatusOK, destinationResponse{
		Configured: found,
		Type:       string(d.Type),
		Enabled:    d.Enabled,
		RemotePath: d.RemotePath,
		Params:     d.MaskedParams(),
	})
}

func (h *BackupDestinationHandler) put(w http.ResponseWriter, r *http.Request, tenantID *uuid.UUID) {
	var req upsertDestinationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid request body")
		return
	}

	d := destination.Destination{
		Type:       destination.Type(req.Type),
		Enabled:    req.Enabled,
		RemotePath: req.RemotePath,
		Params:     req.Params,
	}
	// Validate type + required params BEFORE persisting (never echoes secrets).
	if err := d.Validate(); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}

	if err := h.store.Store(r.Context(), tenantID, d); err != nil {
		// store() already avoids logging credential material; do the same here.
		h.log.Error("failed to store backup destination", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "save_failed", "failed to save backup destination")
		return
	}

	// Re-read the persisted+decrypted value so the response is the masked truth.
	h.get(w, r, tenantID)
}

func (h *BackupDestinationHandler) test(w http.ResponseWriter, r *http.Request) {
	var req upsertDestinationRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid request body")
		return
	}
	d := destination.Destination{
		Type:       destination.Type(req.Type),
		Enabled:    req.Enabled,
		RemotePath: req.RemotePath,
		Params:     req.Params,
	}
	res := h.uploader.TestConnection(r.Context(), d)
	status := http.StatusOK
	if !res.OK {
		status = http.StatusBadRequest
	}
	writeJSON(w, status, res)
}
