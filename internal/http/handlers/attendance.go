package handlers

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
)

// Attendance RBAC permission codes.
const (
	permAttendanceView   = "hrm.attendance.view"
	permAttendanceManage = "hrm.attendance.manage"
)

// AttendanceHandler serves /api/v1/hrm/attendance/*.
type AttendanceHandler struct {
	log *zap.Logger
	svc *attendance.Service
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
		ar.Delete("/rules/{id}", h.DeleteRule)

		// Rotations.
		ar.Get("/rotations", h.ListRotations)
		ar.Post("/rotations", h.CreateRotation)
		ar.Delete("/rotations/{id}", h.DeleteRotation)

		// Off days.
		ar.Get("/off-days", h.ListOffDays)
		ar.Post("/off-days", h.CreateOffDay)
		ar.Delete("/off-days/{id}", h.DeleteOffDay)

		// ESS settings (per-tenant).
		ar.Get("/ess-settings", h.GetESS)
		ar.Put("/ess-settings", h.UpdateESS)

		// Roster + timesheets (registered in attendance_roster.go).
		h.registerRosterRoutes(ar)
		h.registerTimesheetRoutes(ar)
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
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
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
	empID := optionalUUIDParam(r, "employee_id")
	var from, to *time.Time
	if d, err := parseDate(r.URL.Query().Get("from")); err == nil {
		from = &d
	}
	if d, err := parseDate(r.URL.Query().Get("to")); err == nil {
		to = &d
	}
	rows, err := h.svc.ListRecords(r.Context(), scope.TenantID, empID, from, to)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list records")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type checkInBody struct {
	EmployeeID  string `json:"employee_id"`
	WorkShiftID string `json:"work_shift_id"`
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
	date, err := parseDate(b.Date)
	if err != nil {
		date = time.Now().UTC().Truncate(24 * time.Hour)
	}
	checkIn := time.Now().UTC()
	if b.CheckIn != "" {
		if t, perr := time.Parse(time.RFC3339, b.CheckIn); perr == nil {
			checkIn = t.UTC()
		}
	}
	in := attendance.CheckInInput{
		EmployeeID: empID, Date: date, CheckIn: checkIn,
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
	Name                   string `json:"name"`
	RuleType               string `json:"rule_type"`
	Description            string `json:"description"`
	IsActive               *bool  `json:"is_active"`
	Priority               int    `json:"priority"`
	LateThresholdMinutes   int    `json:"late_threshold_minutes"`
	LatePenaltyType        string `json:"late_penalty_type"`
	OvertimeThresholdHours string `json:"overtime_threshold_hours"`
	OvertimeRateMultiplier string `json:"overtime_rate_multiplier"`
	MaxOvertimeHours       string `json:"max_overtime_hours"`
	StandardWorkHours      string `json:"standard_work_hours"`
	MinWorkHours           string `json:"min_work_hours"`
	MaxWorkHours           string `json:"max_work_hours"`
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
	if b.Priority == 0 {
		b.Priority = 100
	}
	row, err := h.svc.CreateRule(r.Context(), scope.TenantID, attendance.RuleInput{
		Name: b.Name, RuleType: b.RuleType, Description: b.Description,
		IsActive: b.IsActive == nil || *b.IsActive, Priority: b.Priority,
		LateThresholdMinutes: b.LateThresholdMinutes, LatePenaltyType: b.LatePenaltyType,
		OvertimeThresholdHours: b.OvertimeThresholdHours, OvertimeRateMultiplier: b.OvertimeRateMultiplier,
		MaxOvertimeHours: b.MaxOvertimeHours, StandardWorkHours: b.StandardWorkHours,
		MinWorkHours: b.MinWorkHours, MaxWorkHours: b.MaxWorkHours,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
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
	writePagedSlice(w, rows, pagination.Parse(r))
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
	ids := make([]uuid.UUID, 0, len(b.ShiftIDs))
	for _, s := range b.ShiftIDs {
		if id, err := uuid.Parse(s); err == nil {
			ids = append(ids, id)
		}
	}
	row, err := h.svc.CreateRotation(r.Context(), scope.TenantID, attendance.RotationInput{
		Title: b.Title, ShiftIDs: ids, RunDuration: b.RunDuration, RunUnit: b.RunUnit,
		BreakDuration: b.BreakDuration, BreakUnit: b.BreakUnit, IsActive: b.IsActive == nil || *b.IsActive,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
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
	writePagedSlice(w, rows, pagination.Parse(r))
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
	var b offDayBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	date, err := parseDate(b.Date)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid date")
		return
	}
	row, err := h.svc.CreateOffDay(r.Context(), scope.TenantID, empID, date, b.Reason)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
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
