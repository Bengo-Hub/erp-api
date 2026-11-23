package handlers

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/Bengo-Hub/httpware/geo"
	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// registerWorkSiteRoutes mounts geo-fenced work site management.
func (h *AttendanceHandler) registerWorkSiteRoutes(ar chi.Router) {
	ar.Get("/work-sites", h.ListWorkSites)
	ar.Post("/work-sites", h.CreateWorkSite)
	ar.Patch("/work-sites/{id}", h.UpdateWorkSite)
	ar.Delete("/work-sites/{id}", h.DeleteWorkSite)
}

type workSiteBody struct {
	Name     *string        `json:"name"`
	OutletID *string        `json:"outlet_id"`
	Center   *geo.Point     `json:"center"`
	RadiusM  *float64       `json:"radius_m"`
	Ring     *[][]float64   `json:"ring"`
	Holes    *[][][]float64 `json:"holes"`
	Active   *bool          `json:"active"`
}

func (b workSiteBody) input() (attendance.WorkSiteInput, error) {
	in := attendance.WorkSiteInput{Name: b.Name, Center: b.Center, RadiusM: b.RadiusM, Ring: b.Ring, Holes: b.Holes, Active: b.Active}
	if b.OutletID != nil && *b.OutletID != "" {
		id, err := uuid.Parse(*b.OutletID)
		if err != nil {
			return in, errors.New("invalid outlet_id")
		}
		in.OutletID = &id
	}
	return in, nil
}

func (h *AttendanceHandler) ListWorkSites(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	rows, err := h.svc.ListWorkSites(r.Context(), scope.TenantID, r.URL.Query().Get("active") == "true")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list work sites")
		return
	}
	writePagedSlice(w, attendance.WorkSiteViews(rows), pagination.Parse(r))
}

func (h *AttendanceHandler) CreateWorkSite(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b workSiteBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := b.input()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	row, err := h.svc.CreateWorkSite(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_work_site", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, attendance.NewWorkSiteView(row))
}

func (h *AttendanceHandler) UpdateWorkSite(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b workSiteBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := b.input()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	row, err := h.svc.UpdateWorkSite(r.Context(), scope.TenantID, id, in)
	if errors.Is(err, attendance.ErrWorkSiteNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "work site not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_work_site", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, attendance.NewWorkSiteView(row))
}

func (h *AttendanceHandler) DeleteWorkSite(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteWorkSite(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", "work site not found")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
