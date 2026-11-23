package handlers

import (
	"context"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/docs"
	"github.com/Bengo-Hub/erp-api/internal/modules/reports"
)

// attendanceReport is an attendance report producer over a date range.
type attendanceReport func(ctx context.Context, tenantID uuid.UUID, f reports.AttendanceFilter) (*reports.Report, error)

// attendanceProducers maps the attendance report types to their producers; GET and export
// share it.
func (h *ReportsHandler) attendanceProducers() map[string]attendanceReport {
	return map[string]attendanceReport{
		"attendance-register": h.svc.AttendanceRegister,
		"absenteeism":         h.svc.Absenteeism,
		"lateness":            h.svc.Lateness,
		"early-leave":         h.svc.EarlyLeave,
		"overtime":            h.svc.Overtime,
		"piece-output":        h.svc.PieceOutputReport,
		"access-log":          h.svc.AccessLog,
		"device-health":       h.svc.DeviceHealth,
		"attendance-summary":  h.svc.AttendanceSummary,
	}
}

// registerAttendanceReports mounts GET /reports/<type> for each attendance report and the
// attendance dashboard.
func (h *ReportsHandler) registerAttendanceReports(rr chi.Router) {
	for name, fn := range h.attendanceProducers() {
		rr.Get("/"+name, h.attendanceHandler(fn))
	}
	rr.Get("/attendance-analytics", h.AttendanceAnalytics)
}

// attendanceFilter parses from, to (YYYY-MM-DD), department_id, outlet_id and employee_id.
func attendanceFilter(r *http.Request) (reports.AttendanceFilter, error) {
	from, to := dateRangeParams(r)
	return reports.NewAttendanceFilter(from, to, optionalUUIDParam(r, "department_id"),
		optionalUUIDParam(r, "outlet_id"), optionalUUIDParam(r, "employee_id"))
}

func (h *ReportsHandler) attendanceHandler(fn attendanceReport) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		scope, ok := scopeFromRequest(w, r)
		if !ok || !requirePermission(w, scope, permReportsView) {
			return
		}
		f, err := attendanceFilter(r)
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", err.Error())
			return
		}
		rep, err := fn(r.Context(), scope.TenantID, f)
		if err != nil {
			h.log.Error("attendance report", zap.Error(err))
			writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate report")
			return
		}
		writeJSON(w, http.StatusOK, rep)
	}
}

// exportAttendance renders an attendance report as CSV, PDF or Excel.
func (h *ReportsHandler) exportAttendance(w http.ResponseWriter, r *http.Request, scope RequestScope, reportType string, fn attendanceReport) {
	f, err := attendanceFilter(r)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	rep, err := fn(r.Context(), scope.TenantID, f)
	if err != nil {
		h.log.Error("attendance report export", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to generate report")
		return
	}
	rawFormat := defaultStr(r.URL.Query().Get("format"), "pdf")
	name := reportType + "-" + f.From.Format("20060102") + "-" + f.To.Format("20060102")
	if rawFormat == "csv" {
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
		h.log.Error("attendance report render", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to render report")
		return
	}
	streamDownload(w, body, mime, filename)
}

// AttendanceAnalytics serves the attendance dashboard: today's figures, a 30-day trend, the
// day by department, month overtime and piece output, and device status.
func (h *ReportsHandler) AttendanceAnalytics(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permReportsView) {
		return
	}
	day, _ := parseDate(r.URL.Query().Get("date")) // zero means today in the company zone
	out, err := h.svc.AttendanceAnalytics(r.Context(), scope.TenantID, day,
		optionalUUIDParam(r, "outlet_id"), optionalUUIDParam(r, "department_id"))
	if err != nil {
		h.log.Error("attendance analytics", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load attendance analytics")
		return
	}
	writeJSON(w, http.StatusOK, out)
}
