package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

// registerAttendanceDeductionRoutes mounts the attendance deduction review under /hrm/payroll.
func (h *PayrollHandler) registerAttendanceDeductionRoutes(pr chi.Router) {
	pr.Get("/attendance-deductions", h.ListAttendanceDeductions)
	pr.Post("/attendance-deductions/compute", h.ComputeAttendanceDeductions)
	pr.Post("/attendance-deductions/review", h.ReviewAttendanceDeductions)
}

func monthParam(v string) (time.Time, bool) {
	if v == "" {
		n := time.Now().UTC()
		return time.Date(n.Year(), n.Month(), 1, 0, 0, 0, 0, time.UTC), true
	}
	m, err := time.Parse("2006-01", v)
	return m, err == nil
}

// ListAttendanceDeductions pages a month's lateness and absence deductions, largest first
// (?month=YYYY-MM&status=pending|approved|waived|applied&employee_id=). The response adds
// amount_total, the sum over every matching row.
func (h *PayrollHandler) ListAttendanceDeductions(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollView) {
		return
	}
	q := r.URL.Query()
	month, ok := monthParam(q.Get("month"))
	if !ok {
		writeError(w, http.StatusBadRequest, "bad_request", "month must be YYYY-MM")
		return
	}
	f := payroll.AttendanceDeductionFilter{Month: month, Status: q.Get("status")}
	switch f.Status {
	case "", "pending", "approved", "waived", "applied":
	default:
		writeError(w, http.StatusBadRequest, "bad_request", "status must be pending, approved, waived or applied")
		return
	}
	if v := q.Get("employee_id"); v != "" {
		id, err := uuid.Parse(v)
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
			return
		}
		f.EmployeeID = &id
	}
	p := pagination.Parse(r)
	f.Limit, f.Offset = p.Limit, p.Offset
	rows, total, amount, err := h.svc.ListAttendanceDeductions(r.Context(), scope.TenantID, f)
	if err != nil {
		h.log.Error("list attendance deductions failed", zapErr(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list attendance deductions")
		return
	}
	resp := pagination.NewResponse(rows, total, p)
	writeJSON(w, http.StatusOK, map[string]any{
		"data": resp.Data, "total": resp.Total, "limit": resp.Limit, "page": resp.Page, "hasMore": resp.HasMore,
		"amount_total": amount.StringFixed(2),
	})
}

// ComputeAttendanceDeductions rebuilds the month's pending deductions from attendance
// ({"month":"YYYY-MM"}). Reviewed rows are left as they are.
func (h *PayrollHandler) ComputeAttendanceDeductions(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollProcess) {
		return
	}
	var body struct {
		Month string `json:"month"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	month, ok := monthParam(body.Month)
	if !ok {
		writeError(w, http.StatusBadRequest, "bad_request", "month must be YYYY-MM")
		return
	}
	sum, err := h.svc.ComputeAttendanceDeductions(r.Context(), scope.TenantID, month)
	if err != nil {
		h.log.Error("compute attendance deductions failed", zapErr(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to compute attendance deductions")
		return
	}
	writeJSON(w, http.StatusOK, sum)
}

// ReviewAttendanceDeductions approves, waives or reopens rows
// ({"ids":[...],"action":"approve|waive|reopen","note":"..."}).
func (h *PayrollHandler) ReviewAttendanceDeductions(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollProcess) {
		return
	}
	var body struct {
		IDs    []uuid.UUID `json:"ids"`
		Action string      `json:"action"`
		Note   string      `json:"note"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || len(body.IDs) == 0 {
		writeError(w, http.StatusBadRequest, "bad_request", "ids and action are required")
		return
	}
	n, err := h.svc.ReviewAttendanceDeductions(r.Context(), scope.TenantID, scope.UserID, body.IDs, body.Action, body.Note)
	if errors.Is(err, payroll.ErrDeductionState) {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	if err != nil {
		h.log.Error("review attendance deductions failed", zapErr(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to review attendance deductions")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"updated": n})
}
