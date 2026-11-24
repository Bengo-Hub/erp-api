package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// Per-employee earnings and deductions: the opt-in payroll components an organisation switched on,
// given to one employee with their own amount or percentage, months and reference. Served under
// /api/v1/hrm/payroll-settings/employees/{employeeId}/components.

// assignmentBody is the create/update payload. Months are "YYYY-MM" (a full date is accepted).
type assignmentBody struct {
	ComponentID string  `json:"component_id"`
	Amount      *string `json:"amount"`
	Percentage  *string `json:"percentage"`
	PercentOf   string  `json:"percent_of"`
	Reference   string  `json:"reference"`
	StartMonth  string  `json:"start_month"`
	EndMonth    string  `json:"end_month"`
	IsActive    *bool   `json:"is_active"`
}

// parseMonth reads "YYYY-MM" or "YYYY-MM-DD"; empty is nil.
func parseMonth(s, field string) (*time.Time, error) {
	s = strings.TrimSpace(s)
	if s == "" {
		return nil, nil
	}
	for _, layout := range []string{"2006-01", "2006-01-02"} {
		if t, err := time.Parse(layout, s); err == nil {
			return &t, nil
		}
	}
	return nil, errors.New(field + " must be a month (YYYY-MM)")
}

func optDecimal(s *string, field string) (*decimal.Decimal, error) {
	if s == nil || strings.TrimSpace(*s) == "" {
		return nil, nil
	}
	d, err := decimal.NewFromString(strings.TrimSpace(*s))
	if err != nil {
		return nil, errors.New(field + " must be a number")
	}
	return &d, nil
}

func (b assignmentBody) toInput() (payrollsettings.AssignmentInput, error) {
	var in payrollsettings.AssignmentInput
	var err error
	if b.ComponentID != "" {
		if in.ComponentID, err = uuid.Parse(b.ComponentID); err != nil {
			return in, errors.New("component_id is invalid")
		}
	}
	if in.Amount, err = optDecimal(b.Amount, "amount"); err != nil {
		return in, err
	}
	if in.Percentage, err = optDecimal(b.Percentage, "percentage"); err != nil {
		return in, err
	}
	if in.StartMonth, err = parseMonth(b.StartMonth, "start_month"); err != nil {
		return in, err
	}
	if in.EndMonth, err = parseMonth(b.EndMonth, "end_month"); err != nil {
		return in, err
	}
	in.PercentOf, in.Reference, in.IsActive = b.PercentOf, b.Reference, b.IsActive
	return in, nil
}

// assignmentView serialises one assignment with its component as the tenant sees it.
func assignmentView(a payrollsettings.Assignment) map[string]any {
	r := a.Row
	v := map[string]any{
		"id":          r.ID,
		"employee_id": r.EmployeeID,
		"is_active":   r.IsActive,
		"amount":      a.Terms.Amount.StringFixed(2),
		"percentage":  a.Terms.Percentage.StringFixed(2),
		"percent_of":  a.Terms.Base,
		"reference":   a.Terms.Reference,
		"calculation": "amount",
		"created_at":  r.CreatedAt.Format(time.RFC3339),
	}
	if a.Terms.Percentage.IsPositive() {
		v["calculation"] = "percentage"
	}
	if r.ComponentID != nil {
		v["component_id"] = *r.ComponentID
	}
	if r.EffectiveDate != nil {
		v["start_month"] = r.EffectiveDate.Format("2006-01")
	}
	if r.EndDate != nil {
		v["end_month"] = r.EndDate.Format("2006-01")
	}
	if rc := a.Component; rc != nil {
		c := rc.Component
		v["code"] = rc.Code
		v["title"] = rc.Title
		v["category"] = c.Category
		v["is_taxable"] = c.TaxableStatus != "nontaxable"
		v["non_cash"] = c.NonCash
		v["deduction_phase"] = c.DeductionPhase
		v["reference_label"] = payrollsettings.ReferenceLabel(rc.Code)
		// component_active is false when the organisation has switched the component off since:
		// the assignment is kept but payroll runs stop applying it.
		v["component_active"] = rc.Active
	} else {
		v["title"] = "Removed component"
		v["component_active"] = false
	}
	return v
}

// employeeParam reads the {employeeId} path parameter.
func employeeParam(w http.ResponseWriter, r *http.Request) (uuid.UUID, bool) {
	id, err := uuid.Parse(chi.URLParam(r, "employeeId"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee id")
		return uuid.Nil, false
	}
	return id, true
}

// ListEmployeeComponents lists the earnings, deductions and benefits assigned to an employee.
func (h *PayrollSettingsHandler) ListEmployeeComponents(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	empID, ok := employeeParam(w, r)
	if !ok {
		return
	}
	rows, err := h.svc.ListAssignments(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list the employee's components")
		return
	}
	out := make([]map[string]any, 0, len(rows))
	for _, a := range rows {
		out = append(out, assignmentView(a))
	}
	writeJSON(w, http.StatusOK, map[string]any{"results": out, "count": len(out)})
}

// SaveEmployeeComponent creates (POST) or updates (PUT .../{id}) an assignment.
func (h *PayrollSettingsHandler) SaveEmployeeComponent(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	empID, ok := employeeParam(w, r)
	if !ok {
		return
	}
	var id *uuid.UUID
	if raw := chi.URLParam(r, "id"); raw != "" {
		parsed, err := uuid.Parse(raw)
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
			return
		}
		id = &parsed
	}
	var b assignmentBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := b.toInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	if id == nil && in.ComponentID == uuid.Nil {
		writeError(w, http.StatusBadRequest, "bad_request", "component_id is required")
		return
	}
	a, err := h.svc.SaveAssignment(r.Context(), scope.TenantID, empID, id, in)
	if err != nil {
		if errors.Is(err, payrollsettings.ErrNotAssignable) {
			writeError(w, http.StatusUnprocessableEntity, "not_assignable", err.Error())
			return
		}
		writeSettingsError(w, err, "invalid_assignment")
		return
	}
	status := http.StatusOK
	if id == nil {
		status = http.StatusCreated
	}
	writeJSON(w, status, assignmentView(*a))
}

// DeleteEmployeeComponent removes an assignment (payslips already generated keep their lines).
func (h *PayrollSettingsHandler) DeleteEmployeeComponent(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	empID, ok := employeeParam(w, r)
	if !ok {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteAssignment(r.Context(), scope.TenantID, empID, id); err != nil {
		writeSettingsError(w, err, "delete_failed")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
