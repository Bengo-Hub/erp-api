package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"

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
		dr.Get("/cost-center-check", h.CostCenterCheck)
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
		jr.Delete("/{id}/customisation", h.RevertJobGroup)
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
	// CostCenterID (departments only) is the treasury cost center for unallocated payroll cost.
	CostCenterID *string `json:"cost_center_id,omitempty"`
	// Grade and the salary range (job groups only).
	Grade     string `json:"grade,omitempty"`
	MinSalary string `json:"min_salary,omitempty"`
	MaxSalary string `json:"max_salary,omitempty"`
	// Inherited and Customised (job groups only): a platform job group, and whether the company
	// changed it.
	Inherited  bool `json:"inherited"`
	Customised bool `json:"customised"`
}

func deptView(d *ent.Department) namedView {
	v := namedView{ID: d.ID, Name: d.Title, Title: d.Title, Code: d.Code, Description: orgsettings.ExtraOf(d.Metadata, orgsettings.ExtraDescription)}
	if d.CostCenterID != nil {
		v.CostCenterID = strPtr(d.CostCenterID.String())
	}
	if d.TenantID != nil {
		s := d.TenantID.String()
		v.TenantID = &s
	}
	v.CreatedAt = d.CreatedAt.Format("2006-01-02T15:04:05Z07:00")
	return v
}

func titleView(t *ent.JobTitle) namedView {
	v := namedView{ID: t.ID, Name: t.Title, Title: t.Title, TenantID: strPtr(t.TenantID.String()),
		Code: orgsettings.ExtraOf(t.Metadata, orgsettings.ExtraCode)}
	if t.Description != nil {
		v.Description = *t.Description
	}
	v.CreatedAt = t.CreatedAt.Format("2006-01-02T15:04:05Z07:00")
	return v
}

func groupView(g *ent.JobGroup) namedView {
	v := namedView{ID: g.ID, Name: g.Title, Title: g.Title, TenantID: strPtr(g.TenantID.String()),
		Grade:     orgsettings.ExtraOf(g.Metadata, orgsettings.ExtraGrade),
		MinSalary: orgsettings.ExtraOf(g.Metadata, orgsettings.ExtraMinSalary),
		MaxSalary: orgsettings.ExtraOf(g.Metadata, orgsettings.ExtraMaxSalary)}
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
	Name        string  `json:"name"`
	Title       string  `json:"title"`
	Code        *string `json:"code"`
	Description *string `json:"description"`
	// Grade and the salary range (job groups only).
	Grade     *string `json:"grade"`
	MinSalary *string `json:"min_salary"`
	MaxSalary *string `json:"max_salary"`
	// CostCenterID (departments only): absent leaves it unchanged, "" clears it, an id sets it.
	CostCenterID *string `json:"cost_center_id"`
}

func (b namedBody) toInput() orgsettings.NamedInput {
	title := b.Name
	if title == "" {
		title = b.Title
	}
	in := orgsettings.NamedInput{Title: title, Extra: map[string]string{}}
	for key, v := range map[string]*string{orgsettings.ExtraCode: b.Code, orgsettings.ExtraDescription: b.Description,
		orgsettings.ExtraGrade: b.Grade, orgsettings.ExtraMinSalary: b.MinSalary, orgsettings.ExtraMaxSalary: b.MaxSalary} {
		if v != nil {
			in.Extra[key] = strings.TrimSpace(*v)
		}
	}
	if b.Code != nil {
		in.Code = strings.TrimSpace(*b.Code)
	}
	if b.Description != nil {
		in.Description = *b.Description
	}
	if b.CostCenterID != nil {
		in.CostCenterSet = true
		if id, err := uuid.Parse(*b.CostCenterID); err == nil {
			in.CostCenterID = &id
		}
	}
	return in
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

// CostCenterCheck returns the last nightly comparison of the tenant's department and project
// allocation cost centres with treasury: ids treasury no longer has, or has deactivated.
func (h *OrgSettingsHandler) CostCenterCheck(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	res, err := h.svc.LastCostCenterCheck(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to read the cost centre check")
		return
	}
	writeJSON(w, http.StatusOK, res)
}

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
		if strings.Contains(err.Error(), "not found") {
			writeError(w, http.StatusNotFound, "not_found", "department not found")
			return
		}
		h.log.Error("delete department failed", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "delete_failed", "failed to delete department")
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
	rows, err := h.svc.JobGroupRows(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list job groups")
		return
	}
	out := make([]namedView, 0, len(rows))
	for _, g := range rows {
		out = append(out, groupRowView(g))
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
	g, err := h.svc.JobGroupRowByID(r.Context(), scope.TenantID, id)
	if errors.Is(err, orgsettings.ErrJobGroupNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "job group not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch job group")
		return
	}
	writeJSON(w, http.StatusOK, groupRowView(*g))
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
	if errors.Is(err, orgsettings.ErrJobGroupNotFound) || ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "job group not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, groupRowView(*g))
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
		if errors.Is(err, orgsettings.ErrInheritedJobGroup) {
			writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
			return
		}
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// RevertJobGroup drops the company's changes to an inherited job group.
func (h *OrgSettingsHandler) RevertJobGroup(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.RevertJobGroup(r.Context(), scope.TenantID, id)
	switch {
	case errors.Is(err, orgsettings.ErrJobGroupNotFound):
		writeError(w, http.StatusNotFound, "not_found", err.Error())
	case errors.Is(err, orgsettings.ErrJobGroupNotCustomised):
		writeError(w, http.StatusConflict, "not_customised", err.Error())
	case err != nil:
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to revert the job group")
	default:
		writeJSON(w, http.StatusOK, groupRowView(*row))
	}
}

// groupRowView is a job group with whether the company inherits or changed it.
func groupRowView(row orgsettings.JobGroupRow) namedView {
	v := groupView(row.JobGroup)
	v.Inherited, v.Customised = row.Inherited, row.Customised
	return v
}
