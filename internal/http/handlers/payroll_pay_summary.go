package handlers

import (
	"net/http"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// EmployeePaySummary lists what this month's payroll applies to one employee (statutory items,
// salary, loans, assigned items) with the preview engine's amounts. ?month=YYYY-MM, default the
// current month.
func (h *PayrollHandler) EmployeePaySummary(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	period := firstOfThisMonth()
	if raw := r.URL.Query().Get("month"); raw != "" {
		if period, ok = parsePeriod(raw); !ok {
			writeError(w, http.StatusBadRequest, "bad_request", "month must be YYYY-MM")
			return
		}
	}
	out, err := h.svc.EmployeePaySummary(r.Context(), scope.TenantID, id, period)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "employee not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load the pay summary")
		return
	}
	writeJSON(w, http.StatusOK, out)
}
