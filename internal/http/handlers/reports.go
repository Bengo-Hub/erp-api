package handlers

import (
	"context"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/reports"
)

// Reports RBAC permission code.
const permReportsView = "reports.view"

// ReportsHandler serves /api/v1/reports/* — the erp-ui report-runner backend.
type ReportsHandler struct {
	log *zap.Logger
	svc *reports.Service
}

func NewReportsHandler(log *zap.Logger, svc *reports.Service) *ReportsHandler {
	return &ReportsHandler{log: log.Named("reports"), svc: svc}
}

// periodReport is a payroll-period report producer.
type periodReport func(ctx context.Context, tenantID uuid.UUID, f reports.Filter) (*reports.Report, error)

func (h *ReportsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/reports", func(rr chi.Router) {
		// Statutory payroll returns + payroll schedules (all period-scoped).
		rr.Get("/p9", h.period(h.svc.P9))
		rr.Get("/p10a", h.period(h.svc.P10A))
		rr.Get("/statutory", h.period(h.svc.Statutory))
		rr.Get("/shif", h.period(h.svc.SHIF))
		rr.Get("/nhif", h.period(h.svc.NHIF))
		rr.Get("/nssf", h.period(h.svc.NSSF))
		rr.Get("/nita", h.period(h.svc.NITA))
		rr.Get("/withholding-tax", h.period(h.svc.WithholdingTax))
		rr.Get("/bank-schedule", h.period(h.svc.BankSchedule))
		rr.Get("/payroll-variance", h.period(h.svc.PayrollVariance))
		rr.Get("/payroll-summary", h.period(h.svc.PayrollSummary))

		// Non-period summaries.
		rr.Get("/headcount-summary", h.Headcount)
		rr.Get("/leave-summary", h.LeaveSummary)
	})
}

// period adapts a period-scoped report to an http.HandlerFunc, parsing year/month/outlet.
func (h *ReportsHandler) period(fn periodReport) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		scope, ok := scopeFromRequest(w, r)
		if !ok || !requirePermission(w, scope, permReportsView) {
			return
		}
		year := atoiDefault(r.URL.Query().Get("year"), 0)
		month := atoiDefault(r.URL.Query().Get("month"), 0)
		if year == 0 {
			writeError(w, http.StatusBadRequest, "bad_request", "year is required")
			return
		}
		f, err := reports.ResolvePeriod(year, month, optionalUUIDParam(r, "outlet_id"))
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", err.Error())
			return
		}
		rep, err := fn(r.Context(), scope.TenantID, f)
		if err != nil {
			h.log.Error("report", zap.Error(err))
			writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate report")
			return
		}
		writeJSON(w, http.StatusOK, rep)
	}
}

func (h *ReportsHandler) Headcount(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permReportsView) {
		return
	}
	rep, err := h.svc.HeadcountSummary(r.Context(), scope.TenantID, optionalUUIDParam(r, "outlet_id"))
	if err != nil {
		h.log.Error("headcount", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate report")
		return
	}
	writeJSON(w, http.StatusOK, rep)
}

func (h *ReportsHandler) LeaveSummary(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permReportsView) {
		return
	}
	year := atoiDefault(r.URL.Query().Get("year"), 0)
	if year == 0 {
		writeError(w, http.StatusBadRequest, "bad_request", "year is required")
		return
	}
	rep, err := h.svc.LeaveSummary(r.Context(), scope.TenantID, year)
	if err != nil {
		h.log.Error("leave summary", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate report")
		return
	}
	writeJSON(w, http.StatusOK, rep)
}

// atoiDefault parses an int or returns def on empty/invalid.
func atoiDefault(s string, def int) int {
	if s == "" {
		return def
	}
	n, err := strconv.Atoi(s)
	if err != nil {
		return def
	}
	return n
}
