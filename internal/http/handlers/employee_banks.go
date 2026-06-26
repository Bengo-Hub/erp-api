package handlers

import (
	"net/http"

	"github.com/go-chi/chi/v5"
)

// ListBanks proxies the Paystack bank list for a country via treasury S2S.
func (h *EmployeesHandler) ListBanks(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	if h.treasury == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "bank verification not configured")
		return
	}
	raw, err := h.treasury.ListBanks(r.Context(), scope.TenantID, chi.URLParam(r, "country"))
	if err != nil {
		writeError(w, http.StatusBadGateway, "banks_failed", "failed to load banks")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(raw)
}

// ResolveBankAccount proxies Paystack account name-enquiry via treasury S2S.
func (h *EmployeesHandler) ResolveBankAccount(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permEmployeeView) {
		return
	}
	if h.treasury == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "bank verification not configured")
		return
	}
	raw, err := h.treasury.ResolveAccount(r.Context(), scope.TenantID, r.URL.Query().Get("account_number"), r.URL.Query().Get("bank_code"))
	if err != nil {
		writeError(w, http.StatusBadGateway, "resolve_failed", "failed to verify account")
		return
	}
	w.Header().Set("Content-Type", "application/json")
	_, _ = w.Write(raw)
}
