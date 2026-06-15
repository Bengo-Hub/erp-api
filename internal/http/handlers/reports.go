package handlers

import (
	"context"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/docs"
	"github.com/Bengo-Hub/erp-api/internal/modules/reports"
)

// Reports RBAC permission code.
const permReportsView = "reports.view"

// ReportsHandler serves /api/v1/reports/* — the erp-ui report-runner backend.
type ReportsHandler struct {
	log  *zap.Logger
	svc  *reports.Service
	docs *DocumentsHandler // optional: enables PDF/Excel export when wired
}

func NewReportsHandler(log *zap.Logger, svc *reports.Service) *ReportsHandler {
	return &ReportsHandler{log: log.Named("reports"), svc: svc}
}

// SetDocuments wires the document handler so /reports/{type}/export can render the
// report as a tenant-branded PDF/Excel. Call once at startup before mounting routes.
func (h *ReportsHandler) SetDocuments(d *DocumentsHandler) { h.docs = d }

// periodReport is a payroll-period report producer.
type periodReport func(ctx context.Context, tenantID uuid.UUID, f reports.Filter) (*reports.Report, error)

// producers maps the report {type} path segment to its period-scoped producer, reusing
// the same dispatch the GET endpoints use so export stays in lock-step with them.
func (h *ReportsHandler) producers() map[string]periodReport {
	return map[string]periodReport{
		"p9":               h.svc.P9,
		"p10a":             h.svc.P10A,
		"statutory":        h.svc.Statutory,
		"shif":             h.svc.SHIF,
		"nhif":             h.svc.NHIF,
		"nssf":             h.svc.NSSF,
		"nita":             h.svc.NITA,
		"withholding-tax":  h.svc.WithholdingTax,
		"bank-schedule":    h.svc.BankSchedule,
		"payroll-variance": h.svc.PayrollVariance,
		"payroll-summary":  h.svc.PayrollSummary,
	}
}

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

		// Export: run the report then render it as a tenant-branded PDF/Excel.
		rr.Get("/{type}/export", h.Export)
	})
}

// Export runs the report named by {type} and streams it as a PDF (format=pdf) or Excel
// (format=excel|xlsx) document. It reuses the same period-scoped producers as the GET
// endpoints, then adapts the Report → Document → Generate via the documents handler.
func (h *ReportsHandler) Export(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permReportsView) {
		return
	}
	if h.docs == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "export not configured")
		return
	}
	reportType := chi.URLParam(r, "type")
	fn, found := h.producers()[reportType]
	if !found {
		writeError(w, http.StatusNotFound, "not_found", "unknown report type: "+reportType)
		return
	}

	format, err := docs.FormatFromString(defaultStr(r.URL.Query().Get("format"), "pdf"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
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
		h.log.Error("report export", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate report")
		return
	}

	body, mime, filename, err := h.docs.GenerateReport(r.Context(), scope.TenantID, rep, format)
	if err != nil {
		h.log.Error("report export render", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to render report")
		return
	}
	streamDownload(w, body, mime, filename)
}

// defaultStr returns def when s is empty.
func defaultStr(s, def string) string {
	if s == "" {
		return def
	}
	return s
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
