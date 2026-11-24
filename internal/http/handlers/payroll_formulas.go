package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// formulaItemBody is one band in a create/update request.
type formulaItemBody struct {
	AmountFrom       string `json:"amount_from"`
	AmountTo         string `json:"amount_to"`
	DeductAmount     string `json:"deduct_amount"`
	DeductPercentage string `json:"deduct_percentage"`
}

// formulaBody is the create/update payload for a formula + its bands + split.
type formulaBody struct {
	Type               string            `json:"type"`
	Category           string            `json:"category"`
	Title              string            `json:"title"`
	Unit               string            `json:"unit"`
	EffectiveFrom      string            `json:"effective_from"`
	EffectiveTo        string            `json:"effective_to"`
	IsCurrent          bool              `json:"is_current"`
	Progressive        bool              `json:"progressive"`
	PersonalRelief     string            `json:"personal_relief"`
	RegulatorySource   string            `json:"regulatory_source"`
	Items              []formulaItemBody `json:"items"`
	EmployeePercentage *string           `json:"employee_percentage"`
	EmployerPercentage *string           `json:"employer_percentage"`
}

func decOrZero(s string) decimal.Decimal {
	if s == "" {
		return decimal.Zero
	}
	d, err := decimal.NewFromString(s)
	if err != nil {
		return decimal.Zero
	}
	return d
}

func dateOrNil(s string) *time.Time {
	if s == "" {
		return nil
	}
	if t, err := time.Parse("2006-01-02", s); err == nil {
		return &t
	}
	return nil
}

func (b formulaBody) toInput(id *uuid.UUID) payrollsettings.FormulaInput {
	in := payrollsettings.FormulaInput{
		ID:               id,
		Type:             b.Type,
		Category:         b.Category,
		Title:            b.Title,
		Unit:             b.Unit,
		EffectiveFrom:    dateOrNil(b.EffectiveFrom),
		EffectiveTo:      dateOrNil(b.EffectiveTo),
		IsCurrent:        b.IsCurrent,
		Progressive:      b.Progressive,
		PersonalRelief:   decOrZero(b.PersonalRelief),
		RegulatorySource: b.RegulatorySource,
	}
	for _, it := range b.Items {
		in.Items = append(in.Items, payrollsettings.FormulaItemInput{
			AmountFrom:       decOrZero(it.AmountFrom),
			AmountTo:         decOrZero(it.AmountTo),
			DeductAmount:     decOrZero(it.DeductAmount),
			DeductPercentage: decOrZero(it.DeductPercentage),
		})
	}
	if b.EmployeePercentage != nil {
		v := decOrZero(*b.EmployeePercentage)
		in.EmployeePercentage = &v
	}
	if b.EmployerPercentage != nil {
		v := decOrZero(*b.EmployerPercentage)
		in.EmployerPercentage = &v
	}
	return in
}

// formulaDetailView serialises a formula + bands + split for the editor UI. source tells the
// editor whether the tenant may change it (tenant) or must customise it first (platform).
func formulaDetailView(d *payrollsettings.FormulaDetail, source string) map[string]any {
	f := d.Formula
	v := map[string]any{
		"source":          source,
		"id":              f.ID,
		"type":            f.Type,
		"category":        f.Category,
		"title":           f.Title,
		"name":            f.Title,
		"unit":            f.Unit,
		"is_current":      f.IsCurrent,
		"progressive":     f.Progressive,
		"personal_relief": f.PersonalRelief.StringFixed(2),
		"version":         f.Version,
	}
	if f.RegulatorySource != nil {
		v["regulatory_source"] = *f.RegulatorySource
	}
	if f.EffectiveFrom != nil {
		v["effective_from"] = f.EffectiveFrom.Format("2006-01-02")
	}
	if f.EffectiveTo != nil {
		v["effective_to"] = f.EffectiveTo.Format("2006-01-02")
	}
	items := make([]map[string]any, 0, len(d.Items))
	for _, it := range d.Items {
		items = append(items, map[string]any{
			"id":                it.ID,
			"amount_from":       it.AmountFrom.StringFixed(2),
			"amount_to":         it.AmountTo.StringFixed(2),
			"deduct_amount":     it.DeductAmount.StringFixed(2),
			"deduct_percentage": it.DeductPercentage.StringFixed(2),
		})
	}
	v["items"] = items
	if d.Split != nil {
		v["employee_percentage"] = d.Split.EmployeePercentage.StringFixed(2)
		v["employer_percentage"] = d.Split.EmployerPercentage.StringFixed(2)
	}
	return v
}

// GetFormula returns a formula with its bands + split (the editor read model).
func (h *PayrollSettingsHandler) GetFormula(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	tenant := h.settingsTenant(r, scope)
	d, err := h.svc.GetFormulaDetail(r.Context(), tenant, id)
	if ent.IsNotFound(err) || errors.Is(err, payrollsettings.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "formula not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load formula")
		return
	}
	writeJSON(w, http.StatusOK, formulaDetailView(d, h.svc.FormulaSource(tenant, d.Formula)))
}

// CustomiseFormula gives the tenant its own copy of one platform formula to edit.
func (h *PayrollSettingsHandler) CustomiseFormula(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	f, err := h.svc.CustomiseFormula(r.Context(), scope.TenantID, id)
	if err != nil {
		writeSettingsError(w, err, "customise_failed")
		return
	}
	d, err := h.svc.GetFormulaDetail(r.Context(), scope.TenantID, f.ID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "customised but failed to reload")
		return
	}
	writeJSON(w, http.StatusCreated, formulaDetailView(d, payrollsettings.SourceTenant))
}

// RevertFormula removes the tenant's own versions of the formula so the platform default applies.
func (h *PayrollSettingsHandler) RevertFormula(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	n, err := h.svc.RevertFormula(r.Context(), scope.TenantID, id)
	if err != nil {
		writeSettingsError(w, err, "revert_failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"removed": n})
}

// DeleteFormula deletes one of the tenant's own formula rows (platform rows: platform owner with
// scope=platform, and never the current one).
func (h *PayrollSettingsHandler) DeleteFormula(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteFormula(r.Context(), h.settingsTenant(r, scope), id); err != nil {
		writeSettingsError(w, err, "delete_failed")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// CreateFormula creates a formula + bands + split.
func (h *PayrollSettingsHandler) CreateFormula(w http.ResponseWriter, r *http.Request) {
	h.upsertFormula(w, r, nil)
}

// UpdateFormula replaces a formula's metadata + bands + split.
func (h *PayrollSettingsHandler) UpdateFormula(w http.ResponseWriter, r *http.Request) {
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	h.upsertFormula(w, r, &id)
}

func (h *PayrollSettingsHandler) upsertFormula(w http.ResponseWriter, r *http.Request, id *uuid.UUID) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b formulaBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	// A platform owner edits a platform formula in place (it reaches every tenant without its own
	// version); everyone else writes the tenant's own rows, and a platform row must be
	// customised first.
	tenant := h.settingsTenant(r, scope)
	if id != nil && tenant == scope.TenantID && scope.Claims != nil && scope.Claims.IsPlatformOwner {
		if cur, err := h.svc.GetFormulaDetail(r.Context(), tenant, *id); err == nil && h.svc.IsPlatformTenant(cur.Formula.TenantID) {
			tenant = cur.Formula.TenantID
		}
	}
	formula, err := h.svc.UpsertFormula(r.Context(), tenant, b.toInput(id))
	if err != nil {
		writeSettingsError(w, err, "formula_failed")
		return
	}
	d, err := h.svc.GetFormulaDetail(r.Context(), tenant, formula.ID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "saved but failed to reload")
		return
	}
	status := http.StatusOK
	if id == nil {
		status = http.StatusCreated
	}
	writeJSON(w, status, formulaDetailView(d, h.svc.FormulaSource(tenant, d.Formula)))
}
