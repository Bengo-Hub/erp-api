package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
	"github.com/Bengo-Hub/erp-api/internal/platform/media"
)

// Attendance RBAC permission codes.
const (
	permAttendanceView   = "hrm.attendance.view"
	permAttendanceManage = "hrm.attendance.manage"
)

// AttendanceHandler serves /api/v1/hrm/attendance/*.
type AttendanceHandler struct {
	log   *zap.Logger
	svc   *attendance.Service
	media *media.Store // clock-in selfies (attendance_self.go)
}

// WithMedia enables ESS clock-in photo uploads.
func (h *AttendanceHandler) WithMedia(m *media.Store) *AttendanceHandler {
	h.media = m
	return h
}

func NewAttendanceHandler(log *zap.Logger, svc *attendance.Service) *AttendanceHandler {
	return &AttendanceHandler{log: log.Named("hrm.attendance"), svc: svc}
}

func (h *AttendanceHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/attendance", func(ar chi.Router) {
		// Shifts + schedules.
		ar.Get("/shifts", h.ListShifts)
		ar.Post("/shifts", h.CreateShift)
		ar.Post("/shifts/ensure-default", h.EnsureDefaultShift)
		ar.Delete("/shifts/{id}", h.DeleteShift)
		ar.Get("/shifts/{id}/schedules", h.ListSchedules)
		ar.Put("/shifts/{id}/schedules", h.UpsertSchedule)

		// Records.
		ar.Get("/records", h.ListRecords)
		ar.Post("/records/check-in", h.CheckIn)
		ar.Post("/records/{id}/check-out", h.CheckOut)

		// Rules.
		ar.Get("/rules", h.ListRules)
		ar.Post("/rules", h.CreateRule)
		ar.Put("/rules/{id}", h.UpdateRule)
		ar.Patch("/rules/{id}", h.UpdateRule)
		ar.Delete("/rules/{id}", h.DeleteRule)

		// Rotations.
		ar.Get("/rotations", h.ListRotations)
		ar.Post("/rotations", h.CreateRotation)
		ar.Put("/rotations/{id}", h.UpdateRotation)
		ar.Patch("/rotations/{id}", h.UpdateRotation)
		ar.Delete("/rotations/{id}", h.DeleteRotation)

		// Off days.
		ar.Get("/off-days", h.ListOffDays)
		ar.Post("/off-days", h.CreateOffDay)
		ar.Put("/off-days/{id}", h.UpdateOffDay)
		ar.Patch("/off-days/{id}", h.UpdateOffDay)
		ar.Delete("/off-days/{id}", h.DeleteOffDay)

		// ESS settings (per-tenant).
		ar.Get("/ess-settings", h.GetESS)
		ar.Put("/ess-settings", h.UpdateESS)

		// Roster + timesheets (registered in attendance_roster.go).
		h.registerRosterRoutes(ar)
		h.registerTimesheetRoutes(ar)
		// Settings, devices, punches, access events, work sites and ESS clock-in.
		h.registerSettingsRoutes(ar)
		h.registerDeviceRoutes(ar)
		h.registerWorkSiteRoutes(ar)
		h.registerSelfClockRoutes(ar)
		h.registerCorrectionRoutes(ar) // regularisations + overtime requests (S5)

		// Capacity per person and week for projects-api's workload (S2S, attendance_capacity.go).
		ar.Get("/capacity", h.Capacity)
	})
}

// ---- Shifts ----

func (h *AttendanceHandler) ListShifts(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	rows, err := h.svc.ListShifts(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list shifts")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type shiftBody struct {
	Name              string `json:"name"`
	StartTime         string `json:"start_time"`
	EndTime           string `json:"end_time"`
	GraceMinutes      int    `json:"grace_minutes"`
	TotalHoursPerWeek string `json:"total_hours_per_week"`
}

func (h *AttendanceHandler) CreateShift(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b shiftBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.CreateShift(r.Context(), scope.TenantID, attendance.ShiftInput{
		Name: b.Name, StartTime: b.StartTime, EndTime: b.EndTime,
		GraceMinutes: b.GraceMinutes, TotalHoursPerWeek: b.TotalHoursPerWeek,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", clientMessage(err))
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *AttendanceHandler) EnsureDefaultShift(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	row, err := h.svc.EnsureDefaultShift(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *AttendanceHandler) DeleteShift(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteShift(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *AttendanceHandler) ListSchedules(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	rows, err := h.svc.ListSchedules(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list schedules")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type scheduleBody struct {
	Day          string `json:"day"`
	StartTime    string `json:"start_time"`
	EndTime      string `json:"end_time"`
	BreakHours   string `json:"break_hours"`
	IsWorkingDay *bool  `json:"is_working_day"`
}

func (h *AttendanceHandler) UpsertSchedule(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b scheduleBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpsertSchedule(r.Context(), scope.TenantID, id, attendance.ScheduleInput{
		Day: b.Day, StartTime: b.StartTime, EndTime: b.EndTime,
		BreakHours: b.BreakHours, IsWorkingDay: b.IsWorkingDay == nil || *b.IsWorkingDay,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "upsert_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// ---- Records ----

func (h *AttendanceHandler) ListRecords(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	f := attendance.RecordFilter{
		EmployeeID: selfOrParamEmployeeID(r, scope),
		OutletID:   optionalUUIDParam(r, "outlet_id"),
		Status:     r.URL.Query().Get("status"),
	}
	if d, err := parseDate(r.URL.Query().Get("from")); err == nil {
		f.From = &d
	}
	if d, err := parseDate(r.URL.Query().Get("to")); err == nil {
		f.To = &d
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListRecords(r.Context(), scope.TenantID, f, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list records")
		return
	}
	writePaginated(w, h.svc.RecordViews(r.Context(), scope.TenantID, rows), total, p)
}

type checkInBody struct {
	EmployeeID  string `json:"employee_id"`
	WorkShiftID string `json:"work_shift_id"`
	OutletID    string `json:"outlet_id"`
	Date        string `json:"date"`
	CheckIn     string `json:"check_in"`
	BiometricID string `json:"biometric_id"`
	GPSLat      string `json:"gps_latitude"`
	GPSLng      string `json:"gps_longitude"`
}

func (h *AttendanceHandler) CheckIn(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b checkInBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	// No date means the service derives the work day from the check-in in the outlet's zone.
	date, _ := parseDate(b.Date)
	checkIn := time.Now().UTC()
	if b.CheckIn != "" {
		if t, perr := time.Parse(time.RFC3339, b.CheckIn); perr == nil {
			checkIn = t.UTC()
		}
	}
	in := attendance.CheckInInput{
		EmployeeID: empID, Date: date, CheckIn: checkIn, Source: "manual",
		OutletID:    optionalUUIDString(b.OutletID),
		BiometricID: b.BiometricID, GPSLat: b.GPSLat, GPSLng: b.GPSLng,
	}
	if b.WorkShiftID != "" {
		if sid, perr := uuid.Parse(b.WorkShiftID); perr == nil {
			in.WorkShiftID = &sid
		}
	}
	row, err := h.svc.CheckIn(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "checkin_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

type checkOutBody struct {
	CheckOut string `json:"check_out"`
}

func (h *AttendanceHandler) CheckOut(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b checkOutBody
	_ = json.NewDecoder(r.Body).Decode(&b)
	checkOut := time.Now().UTC()
	if b.CheckOut != "" {
		if t, perr := time.Parse(time.RFC3339, b.CheckOut); perr == nil {
			checkOut = t.UTC()
		}
	}
	row, err := h.svc.CheckOut(r.Context(), scope.TenantID, id, checkOut)
	if err != nil {
		writeError(w, http.StatusBadRequest, "checkout_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// ---- Rules ----

func (h *AttendanceHandler) ListRules(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	rows, err := h.svc.ListRules(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list rules")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type ruleBody struct {
	Name                       string `json:"name"`
	RuleType                   string `json:"rule_type"`
	Description                string `json:"description"`
	IsActive                   *bool  `json:"is_active"`
	Priority                   int    `json:"priority"`
	BranchID                   string `json:"branch_id"`
	DepartmentID               string `json:"department_id"`
	LateThresholdMinutes       int    `json:"late_threshold_minutes"`
	LatePenaltyType            string `json:"late_penalty_type"`
	LatePenaltyValue           string `json:"late_penalty_value"`
	OvertimeThresholdHours     string `json:"overtime_threshold_hours"`
	OvertimeRateMultiplier     string `json:"overtime_rate_multiplier"`
	MaxOvertimeHours           string `json:"max_overtime_hours"`
	StandardWorkHours          string `json:"standard_work_hours"`
	MinWorkHours               string `json:"min_work_hours"`
	MaxWorkHours               string `json:"max_work_hours"`
	ConsecutiveAbsentThreshold *int   `json:"consecutive_absent_threshold"`
	MonthlyAbsentThreshold     *int   `json:"monthly_absent_threshold"`
	AbsenteeismAction          string `json:"absenteeism_action"`
	BreakDurationMinutes       *int   `json:"break_duration_minutes"`
	HolidayPayMultiplier       string `json:"holiday_pay_multiplier"`
}

func (h *AttendanceHandler) CreateRule(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b ruleBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.CreateRule(r.Context(), scope.TenantID, b.input())
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", clientMessage(err))
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

// input maps the wire body to the service input (priority 0 means the default 100).
func (b ruleBody) input() attendance.RuleInput {
	if b.Priority == 0 {
		b.Priority = 100
	}
	return attendance.RuleInput{
		Name: b.Name, RuleType: b.RuleType, Description: b.Description,
		IsActive: b.IsActive == nil || *b.IsActive, Priority: b.Priority,
		BranchID: optionalUUIDString(b.BranchID), DepartmentID: optionalUUIDString(b.DepartmentID),
		LateThresholdMinutes: b.LateThresholdMinutes, LatePenaltyType: b.LatePenaltyType,
		LatePenaltyValue:       b.LatePenaltyValue,
		OvertimeThresholdHours: b.OvertimeThresholdHours, OvertimeRateMultiplier: b.OvertimeRateMultiplier,
		MaxOvertimeHours: b.MaxOvertimeHours, StandardWorkHours: b.StandardWorkHours,
		MinWorkHours: b.MinWorkHours, MaxWorkHours: b.MaxWorkHours,
		ConsecutiveAbsentThreshold: b.ConsecutiveAbsentThreshold, MonthlyAbsentThreshold: b.MonthlyAbsentThreshold,
		AbsenteeismAction: b.AbsenteeismAction, BreakDurationMinutes: b.BreakDurationMinutes,
		HolidayPayMultiplier: b.HolidayPayMultiplier,
	}
}

// writeUpdateError answers 404 for a missing (or other-tenant) row and 400 otherwise.
func writeUpdateError(w http.ResponseWriter, err error) {
	if errors.Is(err, attendance.ErrNotFound) {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	writeError(w, http.StatusBadRequest, "update_failed", clientMessage(err))
}

func (h *AttendanceHandler) UpdateRule(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b ruleBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateRule(r.Context(), scope.TenantID, id, b.input())
	if err != nil {
		writeUpdateError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *AttendanceHandler) DeleteRule(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteRule(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Rotations ----

func (h *AttendanceHandler) ListRotations(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	rows, err := h.svc.ListRotations(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list rotations")
		return
	}
	p := pagination.Parse(r)
	page, total := pageWindow(rows, p)
	writePaginated(w, h.svc.RotationViews(r.Context(), scope.TenantID, page), total, p)
}

type rotationBody struct {
	Title         string   `json:"title"`
	ShiftIDs      []string `json:"shift_ids"`
	RunDuration   int      `json:"run_duration"`
	RunUnit       string   `json:"run_unit"`
	BreakDuration int      `json:"break_duration"`
	BreakUnit     string   `json:"break_unit"`
	IsActive      *bool    `json:"is_active"`
}

func (h *AttendanceHandler) CreateRotation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var b rotationBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.CreateRotation(r.Context(), scope.TenantID, b.input())
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", clientMessage(err))
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

// input maps the wire body to the service input; unparseable shift ids are dropped.
func (b rotationBody) input() attendance.RotationInput {
	ids := make([]uuid.UUID, 0, len(b.ShiftIDs))
	for _, s := range b.ShiftIDs {
		if id, err := uuid.Parse(s); err == nil {
			ids = append(ids, id)
		}
	}
	return attendance.RotationInput{
		Title: b.Title, ShiftIDs: ids, RunDuration: b.RunDuration, RunUnit: b.RunUnit,
		BreakDuration: b.BreakDuration, BreakUnit: b.BreakUnit, IsActive: b.IsActive == nil || *b.IsActive,
	}
}

func (h *AttendanceHandler) UpdateRotation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b rotationBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateRotation(r.Context(), scope.TenantID, id, b.input())
	if err != nil {
		writeUpdateError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *AttendanceHandler) DeleteRotation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteRotation(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Off days ----

func (h *AttendanceHandler) ListOffDays(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListOffDays(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list off-days")
		return
	}
	p := pagination.Parse(r)
	page, total := pageWindow(rows, p)
	writePaginated(w, h.svc.OffDayViews(r.Context(), scope.TenantID, page), total, p)
}

type offDayBody struct {
	EmployeeID string `json:"employee_id"`
	Date       string `json:"date"`
	Reason     string `json:"reason"`
}

func (h *AttendanceHandler) CreateOffDay(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	b, empID, date, ok := decodeOffDay(w, r)
	if !ok {
		return
	}
	row, err := h.svc.CreateOffDay(r.Context(), scope.TenantID, empID, date, b.Reason)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", clientMessage(err))
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

// decodeOffDay reads and validates an off-day body, writing the 400 itself on failure.
func decodeOffDay(w http.ResponseWriter, r *http.Request) (offDayBody, uuid.UUID, time.Time, bool) {
	var b offDayBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return b, uuid.Nil, time.Time{}, false
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return b, uuid.Nil, time.Time{}, false
	}
	date, err := parseDate(b.Date)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid date")
		return b, uuid.Nil, time.Time{}, false
	}
	return b, empID, date, true
}

func (h *AttendanceHandler) UpdateOffDay(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	b, empID, date, ok := decodeOffDay(w, r)
	if !ok {
		return
	}
	row, err := h.svc.UpdateOffDay(r.Context(), scope.TenantID, id, empID, date, b.Reason)
	if err != nil {
		writeUpdateError(w, err)
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *AttendanceHandler) DeleteOffDay(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteOffDay(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- ESS settings ----

func (h *AttendanceHandler) GetESS(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceView) {
		return
	}
	row, err := h.svc.GetESSSettings(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load ESS settings")
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *AttendanceHandler) UpdateESS(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAttendanceManage) {
		return
	}
	var patch map[string]any
	if err := json.NewDecoder(r.Body).Decode(&patch); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateESSSettings(r.Context(), scope.TenantID, patch)
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}
