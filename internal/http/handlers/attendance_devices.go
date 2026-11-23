package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// registerDeviceRoutes mounts biometric device management, punches and access events.
func (h *AttendanceHandler) registerDeviceRoutes(ar chi.Router) {
	ar.Get("/devices", h.ListDevices)
	ar.Post("/devices", h.CreateDevice)
	ar.Get("/devices/{id}", h.GetDevice)
	ar.Patch("/devices/{id}", h.UpdateDevice)
	ar.Delete("/devices/{id}", h.DeleteDevice)
	ar.Get("/devices/{id}/commands", h.ListDeviceCommands)
	ar.Post("/devices/{id}/commands", h.CreateDeviceCommand)
	ar.Get("/punches", h.ListPunches)
	ar.Get("/access-events", h.ListAccessEvents)
}

type deviceBody struct {
	Serial     *string        `json:"serial"`
	Name       *string        `json:"name"`
	OutletID   *string        `json:"outlet_id"`
	WorkSiteID *string        `json:"work_site_id"`
	Mode       *string        `json:"mode"`
	Active     *bool          `json:"active"`
	Timezone   *string        `json:"timezone"`
	Options    map[string]any `json:"options"`
	CommKey    *string        `json:"comm_key"`
	// AllowedCIDRs limits which addresses may push as this device (empty list clears it).
	AllowedCIDRs *[]string `json:"allowed_cidrs"`
}

func (b deviceBody) input() (attendance.DeviceInput, error) {
	in := attendance.DeviceInput{Serial: b.Serial, Name: b.Name, Mode: b.Mode, Active: b.Active,
		Timezone: b.Timezone, Options: b.Options, CommKey: b.CommKey, AllowedCIDRs: b.AllowedCIDRs}
	if b.AllowedCIDRs != nil {
		for _, c := range *b.AllowedCIDRs {
			if !attendance.ValidCIDROrAddr(c) {
				return in, errors.New("invalid allowed_cidrs entry: " + c)
			}
		}
	}
	if b.Mode != nil && *b.Mode != "ta" && *b.Mode != "ac" {
		return in, errors.New("mode must be ta or ac")
	}
	for _, f := range []struct {
		v   *string
		dst **uuid.UUID
		n   string
	}{{b.OutletID, &in.OutletID, "outlet_id"}, {b.WorkSiteID, &in.WorkSiteID, "work_site_id"}} {
		if f.v == nil || *f.v == "" {
			continue
		}
		id, err := uuid.Parse(*f.v)
		if err != nil {
			return in, errors.New("invalid " + f.n)
		}
		*f.dst = &id
	}
	return in, nil
}

func (h *AttendanceHandler) deviceError(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, attendance.ErrDeviceNotFound):
		writeError(w, http.StatusNotFound, "not_found", "device not found")
	case errors.Is(err, attendance.ErrSerialTaken):
		writeError(w, http.StatusConflict, "serial_taken", err.Error())
	default:
		writeError(w, http.StatusBadRequest, "device_error", err.Error())
	}
}

func (h *AttendanceHandler) ListDevices(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	rows, err := h.svc.ListDevices(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list devices")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

func (h *AttendanceHandler) GetDevice(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.GetDevice(r.Context(), scope.TenantID, id)
	if err != nil {
		h.deviceError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *AttendanceHandler) CreateDevice(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b deviceBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := b.input()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	row, err := h.svc.CreateDevice(r.Context(), scope.TenantID, in)
	if err != nil {
		h.deviceError(w, err)
		return
	}
	view, err := h.svc.GetDevice(r.Context(), scope.TenantID, row.ID)
	if err != nil {
		h.deviceError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, view)
}

func (h *AttendanceHandler) UpdateDevice(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b deviceBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := b.input()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	if _, err := h.svc.UpdateDevice(r.Context(), scope.TenantID, id, in); err != nil {
		h.deviceError(w, err)
		return
	}
	view, err := h.svc.GetDevice(r.Context(), scope.TenantID, id)
	if err != nil {
		h.deviceError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, view)
}

func (h *AttendanceHandler) DeleteDevice(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteDevice(r.Context(), scope.TenantID, id); err != nil {
		h.deviceError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

type deviceCommandBody struct {
	Type string `json:"type"`
	From string `json:"from"`
	To   string `json:"to"`
}

func (h *AttendanceHandler) CreateDeviceCommand(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b deviceCommandBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in := attendance.CommandInput{Type: b.Type}
	if d, perr := parseDate(b.From); perr == nil {
		in.From = &d
	}
	if d, perr := parseDate(b.To); perr == nil {
		in.To = &d
	}
	if scope.UserID != uuid.Nil {
		uid := scope.UserID
		in.CreatedBy = &uid
	}
	rows, err := h.svc.EnqueueCommand(r.Context(), scope.TenantID, id, in)
	if err != nil {
		h.deviceError(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, map[string]any{"data": rows, "total": len(rows)})
}

func (h *AttendanceHandler) ListDeviceCommands(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListCommands(r.Context(), scope.TenantID, id, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list commands")
		return
	}
	writePaginated(w, rows, total, p)
}

func dateRangeParams(r *http.Request) (from, to *time.Time) {
	if d, err := parseDate(r.URL.Query().Get("from")); err == nil {
		from = &d
	}
	if d, err := parseDate(r.URL.Query().Get("to")); err == nil {
		to = &d
	}
	return from, to
}

func (h *AttendanceHandler) ListPunches(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	f := attendance.PunchFilter{
		DeviceID:   optionalUUIDParam(r, "device_id"),
		EmployeeID: optionalUUIDParam(r, "employee_id"),
		Unmatched:  r.URL.Query().Get("unmatched") == "true",
	}
	f.From, f.To = dateRangeParams(r)
	if v := r.URL.Query().Get("flagged"); v != "" {
		b := v == "true"
		f.Flagged = &b
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListPunches(r.Context(), scope.TenantID, f, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list punches")
		return
	}
	writePaginated(w, h.svc.PunchViews(r.Context(), scope.TenantID, rows), total, p)
}

func (h *AttendanceHandler) ListAccessEvents(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	f := attendance.AccessFilter{DeviceID: optionalUUIDParam(r, "device_id"), Result: r.URL.Query().Get("result")}
	f.From, f.To = dateRangeParams(r)
	if v := r.URL.Query().Get("door"); v != "" {
		if n, err := strconv.Atoi(v); err == nil {
			f.Door = &n
		}
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListAccessEvents(r.Context(), scope.TenantID, f, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list access events")
		return
	}
	writePaginated(w, h.svc.AccessEventViews(r.Context(), scope.TenantID, rows), total, p)
}
