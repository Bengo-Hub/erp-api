package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
)

// registerPieceWorkRoutes mounts piece rates and piece output under /hrm/payroll.
func (h *PayrollHandler) registerPieceWorkRoutes(pr chi.Router) {
	pr.Get("/piece-rates", h.ListPieceRates)
	pr.Post("/piece-rates", h.CreatePieceRate)
	pr.Patch("/piece-rates/{id}", h.UpdatePieceRate)
	pr.Delete("/piece-rates/{id}", h.DeletePieceRate)
	pr.Get("/piece-outputs", h.ListPieceOutputs)
	pr.Post("/piece-outputs", h.CreatePieceOutput)
	pr.Post("/piece-outputs/review", h.ReviewPieceOutputs)
}

// canRecordOutput lets payroll managers and attendance managers (supervisors) record output.
func canRecordOutput(w http.ResponseWriter, scope RequestScope) bool {
	if hasPermission(scope, permAttendanceManage) {
		return true
	}
	return requirePermission(w, scope, permPayrollManage)
}

type pieceRateBody struct {
	Code          *string          `json:"code"`
	Name          *string          `json:"name"`
	Unit          *string          `json:"unit"`
	Rate          *decimal.Decimal `json:"rate"`
	Currency      *string          `json:"currency"`
	DepartmentID  *string          `json:"department_id"`
	EffectiveFrom *string          `json:"effective_from"`
	EffectiveTo   *string          `json:"effective_to"`
	Active        *bool            `json:"active"`
}

func (b pieceRateBody) input() (payroll.PieceRateInput, error) {
	in := payroll.PieceRateInput{Code: b.Code, Name: b.Name, Unit: b.Unit, Rate: b.Rate, Currency: b.Currency, Active: b.Active}
	if b.DepartmentID != nil && *b.DepartmentID != "" {
		id, err := uuid.Parse(*b.DepartmentID)
		if err != nil {
			return in, errors.New("invalid department_id")
		}
		in.DepartmentID = &id
	}
	for _, f := range []struct {
		v   *string
		dst **time.Time
		n   string
	}{{b.EffectiveFrom, &in.EffectiveFrom, "effective_from"}, {b.EffectiveTo, &in.EffectiveTo, "effective_to"}} {
		if f.v == nil || *f.v == "" {
			continue
		}
		d, err := parseDate(*f.v)
		if err != nil {
			return in, errors.New(f.n + " must be YYYY-MM-DD")
		}
		*f.dst = &d
	}
	return in, nil
}

func (h *PayrollHandler) ListPieceRates(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if !hasPermission(scope, permAttendanceView) && !requirePermission(w, scope, permPayrollView) {
		return
	}
	rows, err := h.svc.ListPieceRates(r.Context(), scope.TenantID, r.URL.Query().Get("active") == "true")
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list piece rates")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

func (h *PayrollHandler) CreatePieceRate(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b pieceRateBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := b.input()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	row, err := h.svc.CreatePieceRate(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_piece_rate", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *PayrollHandler) UpdatePieceRate(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b pieceRateBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := b.input()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	row, err := h.svc.UpdatePieceRate(r.Context(), scope.TenantID, id, in)
	if errors.Is(err, payroll.ErrPieceRateNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "piece rate not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_piece_rate", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *PayrollHandler) DeletePieceRate(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeletePieceRate(r.Context(), scope.TenantID, id); err != nil {
		if errors.Is(err, payroll.ErrPieceRateNotFound) {
			writeError(w, http.StatusNotFound, "not_found", "piece rate not found")
			return
		}
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to delete piece rate")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

type pieceOutputBody struct {
	EmployeeID       string          `json:"employee_id"`
	PieceRateID      string          `json:"piece_rate_id"`
	Date             string          `json:"date"`
	Quantity         decimal.Decimal `json:"quantity"`
	RejectedQuantity decimal.Decimal `json:"rejected_quantity"`
	Note             string          `json:"note"`
}

func (h *PayrollHandler) CreatePieceOutput(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !canRecordOutput(w, scope) {
		return
	}
	var b pieceOutputBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err1 := uuid.Parse(b.EmployeeID)
	rateID, err2 := uuid.Parse(b.PieceRateID)
	date, err3 := parseDate(b.Date)
	if err1 != nil || err2 != nil || err3 != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "employee_id, piece_rate_id and date (YYYY-MM-DD) are required")
		return
	}
	in := payroll.PieceOutputInput{EmployeeID: empID, PieceRateID: rateID, Date: date,
		Quantity: b.Quantity, RejectedQuantity: b.RejectedQuantity, Note: b.Note}
	if scope.UserID != uuid.Nil {
		uid := scope.UserID
		in.RecordedBy = &uid
	}
	row, err := h.svc.CreatePieceOutput(r.Context(), scope.TenantID, in)
	switch {
	case errors.Is(err, payroll.ErrPieceRateNotFound):
		writeError(w, http.StatusNotFound, "not_found", "piece rate not found")
	case err != nil:
		writeError(w, http.StatusBadRequest, "invalid_piece_output", err.Error())
	default:
		writeJSON(w, http.StatusCreated, row)
	}
}

func (h *PayrollHandler) ListPieceOutputs(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	if !hasPermission(scope, permAttendanceView) && !requirePermission(w, scope, permPayrollView) {
		return
	}
	now := time.Now().UTC()
	f := payroll.PieceOutputFilter{
		EmployeeID: optionalUUIDParam(r, "employee_id"), PieceRateID: optionalUUIDParam(r, "piece_rate_id"),
		Status: r.URL.Query().Get("status"), From: time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC), To: now,
	}
	if d, err := parseDate(r.URL.Query().Get("from")); err == nil {
		f.From = d
	}
	if d, err := parseDate(r.URL.Query().Get("to")); err == nil {
		f.To = d
	}
	if f.To.Sub(f.From) > 366*24*time.Hour {
		f.From = f.To.AddDate(-1, 0, 0)
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListPieceOutputs(r.Context(), scope.TenantID, f, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list piece output")
		return
	}
	writePaginated(w, rows, total, p)
}

type pieceReviewBody struct {
	IDs    []uuid.UUID `json:"ids"`
	Action string      `json:"action"`
}

func (h *PayrollHandler) ReviewPieceOutputs(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPayrollManage) {
		return
	}
	var b pieceReviewBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	var reviewer *uuid.UUID
	if scope.UserID != uuid.Nil {
		uid := scope.UserID
		reviewer = &uid
	}
	n, err := h.svc.ReviewPieceOutputs(r.Context(), scope.TenantID, reviewer, b.IDs, b.Action)
	if err != nil {
		writeError(w, http.StatusBadRequest, "invalid_review", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"updated": n})
}
