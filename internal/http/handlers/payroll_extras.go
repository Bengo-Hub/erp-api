package handlers

import (
	"net/http"
	"strings"

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
	writeJSON(w, http.StatusOK, advanceView(a, name))
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
	writeJSON(w, http.StatusOK, lossDamageView(l, name))
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
