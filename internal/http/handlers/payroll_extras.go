package handlers

import (
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
	"github.com/Bengo-Hub/erp-api/internal/platform/lookups"
)

func zapErr(err error) zap.Field { return zap.Error(err) }

// toLookupOptions adapts the service's fallback options to the lookups.Option shape so both
// the upstream and fallback paths emit an identical {value,label} envelope.
func toLookupOptions(in []payroll.LookupOption) []lookups.Option {
	out := make([]lookups.Option, 0, len(in))
	for _, o := range in {
		out = append(out, lookups.Option{Value: o.Value, Label: o.Label})
	}
	return out
}

// This file holds the recoverable (advance/loss) approval transitions backing the status tabs,
// and the cost-allocation lookup proxies (projects + cost-centers).

// ---- Advance / loss-damage approval transitions ----

func (h *PayrollHandler) ApproveAdvance(w http.ResponseWriter, r *http.Request) {
	h.setAdvanceApproval(w, r, true)
}

func (h *PayrollHandler) DisapproveAdvance(w http.ResponseWriter, r *http.Request) {
	h.setAdvanceApproval(w, r, false)
}

func (h *PayrollHandler) setAdvanceApproval(w http.ResponseWriter, r *http.Request, approve bool) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	a, err := h.svc.SetAdvanceApproval(r.Context(), scope.TenantID, id, scope.UserID, approve)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "advance not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, a.EmployeeID)
	writeJSON(w, http.StatusOK, h.withRepayPlans(r.Context(), scope.TenantID, advanceView(a, name))[0])
}

func (h *PayrollHandler) ApproveLossDamage(w http.ResponseWriter, r *http.Request) {
	h.setLossDamageApproval(w, r, true)
}

func (h *PayrollHandler) DisapproveLossDamage(w http.ResponseWriter, r *http.Request) {
	h.setLossDamageApproval(w, r, false)
}

func (h *PayrollHandler) setLossDamageApproval(w http.ResponseWriter, r *http.Request, approve bool) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	l, err := h.svc.SetLossDamageApproval(r.Context(), scope.TenantID, id, scope.UserID, approve)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "record not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	name, _ := h.svc.EmployeeLabel(r.Context(), scope.TenantID, l.EmployeeID)
	writeJSON(w, http.StatusOK, h.withRepayPlans(r.Context(), scope.TenantID, lossDamageView(l, name))[0])
}

// LabourCost returns a payroll month's gross pay split by project (?month=YYYY-MM, default this
// month), with project names from projects-api when reachable.
func (h *PayrollHandler) LabourCost(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	month := time.Now().UTC()
	if v := r.URL.Query().Get("month"); v != "" {
		m, err := time.Parse("2006-01", v)
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "month must be YYYY-MM")
			return
		}
		month = m
	}
	rep, err := h.svc.ProjectLabourCost(r.Context(), scope.TenantID, month)
	if err != nil {
		h.log.Error("labour cost failed", zapErr(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to build labour cost")
		return
	}
	names := map[string]string{}
	if h.lookups != nil && h.lookups.ProjectsEnabled() && len(rep.Projects) > 0 {
		if opts, err := h.lookups.Projects(r.Context(), scope.TenantID, bearerToken(r)); err == nil {
			for _, o := range opts {
				names[o.Value] = o.Label
			}
		}
	}
	rows := make([]map[string]any, 0, len(rep.Projects))
	for _, p := range rep.Projects {
		row := map[string]any{"amount": p.Amount.StringFixed(2), "share_pct": p.SharePct, "project_id": nil, "project_name": "Not allocated to a project"}
		if p.ProjectID != nil {
			id := p.ProjectID.String()
			row["project_id"], row["project_name"] = id, names[id]
			if names[id] == "" {
				row["project_name"] = id
			}
		}
		rows = append(rows, row)
	}
	writeJSON(w, http.StatusOK, map[string]any{"month": rep.Month, "total_gross": rep.TotalGross.StringFixed(2), "projects": rows})
}

// ---- Cost-allocation lookups (projects + cost-centers) ----

// bearerToken extracts the raw JWT from the Authorization header (without the "Bearer " prefix)
// so it can be forwarded S2S to the owning service.
func bearerToken(r *http.Request) string {
	h := r.Header.Get("Authorization")
	if h == "" {
		return ""
	}
	if strings.HasPrefix(strings.ToLower(h), "bearer ") {
		return strings.TrimSpace(h[7:])
	}
	return strings.TrimSpace(h)
}

// LookupProjects proxies the tenant's projects from projects-api (JWT-forwarded), falling back
// to distinct project ids already present on ERP records when the upstream is unavailable.
func (h *PayrollHandler) LookupProjects(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	var opts []lookups.Option
	source := "fallback"
	if h.lookups != nil && h.lookups.ProjectsEnabled() {
		if got, err := h.lookups.Projects(r.Context(), scope.TenantID, bearerToken(r)); err == nil {
			opts = got
			source = "projects-service"
		} else {
			h.log.Warn("projects lookup upstream failed, using ERP-derived fallback", zapErr(err))
		}
	}
	if opts == nil {
		fb, err := h.svc.DistinctProjectIDs(r.Context(), scope.TenantID)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "internal_error", "failed to list projects")
			return
		}
		opts = toLookupOptions(fb)
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": opts, "data": opts, "source": source})
}

// LookupCostCenters proxies the tenant's cost-centers from treasury-api (JWT-forwarded), falling
// back to distinct cost-center ids already present on ERP records when the upstream is unavailable.
func (h *PayrollHandler) LookupCostCenters(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	var opts []lookups.Option
	source := "fallback"
	if h.lookups != nil && h.lookups.CostCentersEnabled() {
		if got, err := h.lookups.CostCenters(r.Context(), scope.TenantID, bearerToken(r)); err == nil {
			opts = got
			source = "treasury"
		} else {
			h.log.Warn("cost-centers lookup upstream failed, using ERP-derived fallback", zapErr(err))
		}
	}
	if opts == nil {
		fb, err := h.svc.DistinctCostCenterIDs(r.Context(), scope.TenantID)
		if err != nil {
			writeError(w, http.StatusInternalServerError, "internal_error", "failed to list cost centers")
			return
		}
		opts = toLookupOptions(fb)
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": opts, "data": opts, "source": source})
}
