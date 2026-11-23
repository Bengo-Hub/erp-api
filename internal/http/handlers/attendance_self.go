package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
	"github.com/Bengo-Hub/erp-api/internal/platform/media"
)

// maxPhotoBytes caps a clock-in selfie upload.
const maxPhotoBytes = 5 << 20

// registerSelfClockRoutes mounts the ESS clock-in routes. Any staff member may call them; the
// employee always comes from the caller's token, never from the body.
func (h *AttendanceHandler) registerSelfClockRoutes(ar chi.Router) {
	ar.Get("/me/today", h.MyToday)
	ar.Post("/me/clock-in", h.MyClockIn)
	ar.Post("/me/clock-out", h.MyClockOut)
	ar.Post("/me/photo", h.MyPhoto)
}

// selfEmployee resolves the caller's own employee or writes 403.
func selfEmployee(w http.ResponseWriter, r *http.Request) (RequestScope, uuid.UUID, bool) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return scope, uuid.Nil, false
	}
	if resolveSelfEmployee != nil && scope.Claims != nil {
		if id, found := resolveSelfEmployee(r.Context(), scope.TenantID, scope.Claims.Subject); found {
			return scope, id, true
		}
	}
	writeError(w, http.StatusForbidden, "not_an_employee", "your account is not linked to an employee record")
	return scope, uuid.Nil, false
}

func (h *AttendanceHandler) MyToday(w http.ResponseWriter, r *http.Request) {
	scope, empID, ok := selfEmployee(w, r)
	if !ok {
		return
	}
	out, err := h.svc.Today(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load today's attendance")
		return
	}
	writeJSON(w, http.StatusOK, out)
}

type selfClockBody struct {
	Lat       float64 `json:"lat"`
	Lng       float64 `json:"lng"`
	AccuracyM float64 `json:"accuracy_m"`
	PhotoURL  string  `json:"photo_url"`
	Note      string  `json:"note"`
	Source    string  `json:"source"`
}

func (h *AttendanceHandler) MyClockIn(w http.ResponseWriter, r *http.Request) {
	h.selfClock(w, r, false)
}
func (h *AttendanceHandler) MyClockOut(w http.ResponseWriter, r *http.Request) {
	h.selfClock(w, r, true)
}

func (h *AttendanceHandler) selfClock(w http.ResponseWriter, r *http.Request, out bool) {
	scope, empID, ok := selfEmployee(w, r)
	if !ok {
		return
	}
	var b selfClockBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	// A photo must be one this caller uploaded through /me/photo.
	if b.PhotoURL != "" && !ownPhotoKey(b.PhotoURL, scope.TenantID, empID) {
		writeError(w, http.StatusBadRequest, "bad_request", "photo_url must come from /hrm/attendance/me/photo")
		return
	}
	if len(b.Note) > 500 {
		b.Note = b.Note[:500]
	}
	res, err := h.svc.SelfClock(r.Context(), scope.TenantID, empID, out, attendance.SelfClockInput{
		Lat: b.Lat, Lng: b.Lng, AccuracyM: b.AccuracyM, PhotoURL: b.PhotoURL, Note: b.Note, Source: b.Source,
	})
	switch {
	case errors.Is(err, attendance.ErrOutsideFence):
		writeJSON(w, http.StatusForbidden, map[string]any{"error": err.Error(), "code": "outside_fence", "fence": res.Fence})
	case errors.Is(err, attendance.ErrClockedIn):
		writeJSON(w, http.StatusConflict, map[string]any{"error": err.Error(), "code": "already_clocked_in", "record": res.Record})
	case errors.Is(err, attendance.ErrNotClockedIn):
		writeError(w, http.StatusConflict, "not_clocked_in", err.Error())
	case errors.Is(err, attendance.ErrPhotoRequired), errors.Is(err, attendance.ErrBadLocation):
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
	case errors.Is(err, attendance.ErrEmployeeNotFound):
		writeError(w, http.StatusForbidden, "not_an_employee", err.Error())
	case err != nil:
		h.log.Warn("self clock failed")
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to record attendance")
	default:
		writeJSON(w, http.StatusOK, res)
	}
}

// ownPhotoKey reports whether key is an attendance photo stored for this tenant and employee.
func ownPhotoKey(key string, tenantID, empID uuid.UUID) bool {
	return strings.Contains(key, media.TypeAttendancePhotos) &&
		strings.Contains(key, tenantID.String()) && strings.Contains(key, empID.String())
}

// MyPhoto stores a clock-in selfie (multipart field "file", images only) and returns its url
// for the clock-in or clock-out body.
func (h *AttendanceHandler) MyPhoto(w http.ResponseWriter, r *http.Request) {
	scope, empID, ok := selfEmployee(w, r)
	if !ok {
		return
	}
	if !h.media.Enabled() {
		writeError(w, http.StatusServiceUnavailable, "media_unavailable", "media storage not configured")
		return
	}
	r.Body = http.MaxBytesReader(w, r.Body, maxPhotoBytes+(1<<20))
	if err := r.ParseMultipartForm(maxPhotoBytes); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid multipart form or file too large")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "missing 'file' field")
		return
	}
	defer func() { _ = file.Close() }()
	key, err := h.media.SaveAttendancePhoto(r.Context(), scope.TenantID, empID, header.Filename, file)
	if err != nil {
		writeError(w, http.StatusBadRequest, "upload_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"url": key, "preview_url": h.media.URL(key)})
}
