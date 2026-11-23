package handlers

import (
	"context"
	"encoding/csv"
	"fmt"
	"net/http"
	"strconv"
	"time"

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
		"p9a":              h.svc.P9A,
		"p10":              h.svc.P10,
		"p10a":             h.svc.P10A,
		"statutory":        h.svc.Statutory,
		"shif":             h.svc.SHIF,
		"nhif":             h.svc.NHIF,
		"nssf":             h.svc.NSSF,
		"nssf-sf24":        h.svc.NSSF,
		"nita":             h.svc.NITA,
		"withholding-tax":  h.svc.WithholdingTax,
		"bank-schedule":    h.svc.BankSchedule,
		"payroll-variance": h.svc.PayrollVariance,
		"payroll-summary":  h.svc.PayrollSummary,
		"muster-roll":      h.svc.MusterRoll,
		"housing-levy":     h.svc.HousingLevy,
	}
}

func (h *ReportsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/reports", func(rr chi.Router) {
		// Statutory payroll returns + payroll schedules (all period-scoped).
		rr.Get("/p9", h.period(h.svc.P9))
		rr.Get("/p9a", h.period(h.svc.P9A))
		rr.Get("/p10", h.period(h.svc.P10))
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
		rr.Get("/muster-roll", h.period(h.svc.MusterRoll))
		rr.Get("/housing-levy", h.period(h.svc.HousingLevy))

		// Non-period summaries.
		rr.Get("/headcount-summary", h.Headcount)
		rr.Get("/leave-summary", h.LeaveSummary)
		// Dashboard analytics (headcount breakdowns, contracts expiring, payroll trend).
		rr.Get("/hrm-analytics", h.HRMAnalytics)

		// Attendance reports (from/to ranges) and the attendance dashboard (reports_attendance.go).
		h.registerAttendanceReports(rr)

		// Export: run the report then render it as a tenant-branded PDF/Excel.
		rr.Get("/{type}/export", h.Export)
	})
}

// Export runs the report named by {type} and streams it as a PDF (format=pdf), Excel
// (format=excel|xlsx) or CSV (format=csv — the KRA iTax-upload / spreadsheet format). It reuses
// the same period-scoped producers as the GET endpoints.
func (h *ReportsHandler) Export(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permReportsView) {
		return
	}
	reportType := chi.URLParam(r, "type")
	if afn, ok := h.attendanceProducers()[reportType]; ok {
		h.exportAttendance(w, r, scope, reportType, afn)
		return
	}
	fn, found := h.producers()[reportType]
	if !found {
		writeError(w, http.StatusNotFound, "not_found", "unknown report type: "+reportType)
		return
	}

	rawFormat := defaultStr(r.URL.Query().Get("format"), "pdf")
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

	// CSV (iTax / spreadsheet) is rendered straight from the Report envelope — no docs dependency.
	if rawFormat == "csv" {
		name := reportType + "-" + strconv.Itoa(year)
		if month > 0 {
			name += "-" + strconv.Itoa(month)
		}
		writeReportCSV(w, rep, name+".csv")
		return
	}

	if h.docs == nil {
		writeError(w, http.StatusServiceUnavailable, "unavailable", "export not configured")
		return
	}
	format, err := docs.FormatFromString(rawFormat)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
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

// writeReportCSV streams a Report as CSV using its column order (header row = column keys, then
// one row per Report.Rows entry). Missing cells render empty.
func writeReportCSV(w http.ResponseWriter, rep *reports.Report, filename string) {
	w.Header().Set("Content-Type", "text/csv; charset=utf-8")
	w.Header().Set("Content-Disposition", "attachment; filename=\""+filename+"\"")
	cw := csv.NewWriter(w)
	_ = cw.Write(rep.Columns)
	for _, row := range rep.Rows {
		rec := make([]string, len(rep.Columns))
		for i, col := range rep.Columns {
			if v, ok := row[col]; ok && v != nil {
				rec[i] = fmt.Sprintf("%v", v)
			}
		}
		_ = cw.Write(rec)
	}
	cw.Flush()
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

// HRMAnalytics godoc
// @Summary HR dashboard analytics
// @Description Headcount (active, terminated) by department, gender and employment type; new hires in the period (?from, ?to, default this month); contracts expiring in 30/60/90 days; payroll trend (12 months) and the latest month's payroll by department. All grouped in SQL.
// @Tags reports
// @Produce json
// @Success 200 {object} reports.HRMAnalytics
// @Router /api/v1/{tenant}/reports/hrm-analytics [get]
func (h *ReportsHandler) HRMAnalytics(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permReportsView) {
		return
	}
	now := time.Now()
	from := time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)
	to := now
	if v := r.URL.Query().Get("from"); v != "" {
		if t, err := time.Parse("2006-01-02", v); err == nil {
			from = t
		}
	}
	if v := r.URL.Query().Get("to"); v != "" {
		if t, err := time.Parse("2006-01-02", v); err == nil {
			to = t.Add(24*time.Hour - time.Nanosecond)
		}
	}
	rep, err := h.svc.HRMAnalytics(r.Context(), scope.TenantID, from, to)
	if err != nil {
		h.log.Error("hrm analytics", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to build analytics")
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
