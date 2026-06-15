package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/orgsettings"
)

// OrgSettingsHandler serves HRM reference data:
//   - /hrm/departments
//   - /hrm/employees/job-titles
//   - /hrm/employees/job-groups
//
// It reuses the employee RBAC codes (these are managed by the same HR role).
type OrgSettingsHandler struct {
	log *zap.Logger
	svc *orgsettings.Service
}

func NewOrgSettingsHandler(log *zap.Logger, svc *orgsettings.Service) *OrgSettingsHandler {
	return &OrgSettingsHandler{log: log.Named("hrm.orgsettings"), svc: svc}
}

func (h *OrgSettingsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/departments", func(dr chi.Router) {
		dr.Get("/", h.ListDepartments)
		dr.Post("/", h.CreateDepartment)
		dr.Get("/{id}", h.GetDepartment)
		dr.Put("/{id}", h.UpdateDepartment)
		dr.Patch("/{id}", h.UpdateDepartment)
		dr.Delete("/{id}", h.DeleteDepartment)
	})
	r.Route("/hrm/employees/job-titles", func(jr chi.Router) {
		jr.Get("/", h.ListJobTitles)
		jr.Post("/", h.CreateJobTitle)
		jr.Get("/{id}", h.GetJobTitle)
		jr.Put("/{id}", h.UpdateJobTitle)
		jr.Patch("/{id}", h.UpdateJobTitle)
		jr.Delete("/{id}", h.DeleteJobTitle)
	})
	r.Route("/hrm/employees/job-groups", func(jr chi.Router) {
		jr.Get("/", h.ListJobGroups)
		jr.Post("/", h.CreateJobGroup)
		jr.Get("/{id}", h.GetJobGroup)
		jr.Put("/{id}", h.UpdateJobGroup)
		jr.Patch("/{id}", h.UpdateJobGroup)
		jr.Delete("/{id}", h.DeleteJobGroup)
	})
}

// namedView is the erp-ui-facing shape for a reference record. erp-ui reads
// `name` (mapped from the Ent `title` column) plus the original fields.
type namedView struct {
	ID          uuid.UUID `json:"id"`
	Name        string    `json:"name"`
	Title       string    `json:"title"`
	Code        string    `json:"code,omitempty"`
	Description string    `json:"description,omitempty"`
	TenantID    *string   `json:"tenant_id,omitempty"`
	CreatedAt   string    `json:"created_at,omitempty"`
}

func deptView(d *ent.Department) namedView {
	v := namedView{ID: d.ID, Name: d.Title, Title: d.Title, Code: d.Code}
	if d.TenantID != nil {
		s := d.TenantID.String()
		v.TenantID = &s
	}
	v.CreatedAt = d.CreatedAt.Format("2006-01-02T15:04:05Z07:00")
	return v
}

func titleView(t *ent.JobTitle) namedView {
	v := namedView{ID: t.ID, Name: t.Title, Title: t.Title, TenantID: strPtr(t.TenantID.String())}
	if t.Description != nil {
		v.Description = *t.Description
	}
	v.CreatedAt = t.CreatedAt.Format("2006-01-02T15:04:05Z07:00")
	return v
}

func groupView(g *ent.JobGroup) namedView {
	v := namedView{ID: g.ID, Name: g.Title, Title: g.Title, TenantID: strPtr(g.TenantID.String())}
	if g.Description != nil {
		v.Description = *g.Description
	}
	v.CreatedAt = g.CreatedAt.Format("2006-01-02T15:04:05Z07:00")
	return v
}

func strPtr(s string) *string { return &s }

// namedBody is the create/update payload. erp-ui sends `name`; legacy callers
// may send `title`.
type namedBody struct {
	Name        string `json:"name"`
	Title       string `json:"title"`
	Code        string `json:"code"`
	Description string `json:"description"`
}

func (b namedBody) toInput() orgsettings.NamedInput {
	title := b.Name
	if title == "" {
		title = b.Title
	}
	return orgsettings.NamedInput{Title: title, Code: b.Code, Description: b.Description}
}

func decodeNamed(w http.ResponseWriter, r *http.Request) (orgsettings.NamedInput, bool) {
	var b namedBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return orgsettings.NamedInput{}, false
	}
	return b.toInput(), true
}

// ---- Departments ----

func (h *OrgSettingsHandler) ListDepartments(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	rows, err := h.svc.ListDepartments(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list departments")
		return
	}
	out := make([]namedView, 0, len(rows))
	for _, d := range rows {
		out = append(out, deptView(d))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

func (h *OrgSettingsHandler) GetDepartment(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	d, err := h.svc.GetDepartment(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "department not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch department")
		return
	}
	writeJSON(w, http.StatusOK, deptView(d))
}

func (h *OrgSettingsHandler) CreateDepartment(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	in, ok := decodeNamed(w, r)
	if !ok {
		return
	}
	d, err := h.svc.CreateDepartment(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, deptView(d))
}

func (h *OrgSettingsHandler) UpdateDepartment(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := decodeNamed(w, r)
	if !ok {
		return
	}
	d, err := h.svc.UpdateDepartment(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "department not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, deptView(d))
}

func (h *OrgSettingsHandler) DeleteDepartment(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteDepartment(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Job titles ----

func (h *OrgSettingsHandler) ListJobTitles(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	rows, err := h.svc.ListJobTitles(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list job titles")
		return
	}
	out := make([]namedView, 0, len(rows))
	for _, t := range rows {
		out = append(out, titleView(t))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

func (h *OrgSettingsHandler) GetJobTitle(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	t, err := h.svc.GetJobTitle(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "job title not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch job title")
		return
	}
	writeJSON(w, http.StatusOK, titleView(t))
}

func (h *OrgSettingsHandler) CreateJobTitle(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	in, ok := decodeNamed(w, r)
	if !ok {
		return
	}
	t, err := h.svc.CreateJobTitle(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, titleView(t))
}

func (h *OrgSettingsHandler) UpdateJobTitle(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := decodeNamed(w, r)
	if !ok {
		return
	}
	t, err := h.svc.UpdateJobTitle(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "job title not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, titleView(t))
}

func (h *OrgSettingsHandler) DeleteJobTitle(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteJobTitle(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Job groups ----

func (h *OrgSettingsHandler) ListJobGroups(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	rows, err := h.svc.ListJobGroups(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list job groups")
		return
	}
	out := make([]namedView, 0, len(rows))
	for _, g := range rows {
		out = append(out, groupView(g))
	}
	writePagedSlice(w, out, pagination.Parse(r))
}

func (h *OrgSettingsHandler) GetJobGroup(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	g, err := h.svc.GetJobGroup(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "job group not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch job group")
		return
	}
	writeJSON(w, http.StatusOK, groupView(g))
}

func (h *OrgSettingsHandler) CreateJobGroup(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	in, ok := decodeNamed(w, r)
	if !ok {
		return
	}
	g, err := h.svc.CreateJobGroup(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, groupView(g))
}

func (h *OrgSettingsHandler) UpdateJobGroup(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := decodeNamed(w, r)
	if !ok {
		return
	}
	g, err := h.svc.UpdateJobGroup(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "job group not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, groupView(g))
}

func (h *OrgSettingsHandler) DeleteJobGroup(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteJobGroup(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
