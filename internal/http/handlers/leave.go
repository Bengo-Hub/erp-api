package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
	"strings"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
)

// Leave RBAC permission codes.
const (
	permLeaveView    = "hrm.leave.view"
	permLeaveManage  = "hrm.leave.manage"
	permLeaveApprove = "hrm.leave.approve"
)

// LeaveHandler serves /api/v1/hrm/leave/*.
type LeaveHandler struct {
	log *zap.Logger
	svc *leave.Service
}

func NewLeaveHandler(log *zap.Logger, svc *leave.Service) *LeaveHandler {
	return &LeaveHandler{log: log.Named("hrm.leave"), svc: svc}
}

func (h *LeaveHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/leave", func(lr chi.Router) {
		lr.Get("/categories", h.ListCategories)
		lr.Post("/categories", h.CreateCategory)
		lr.Put("/categories/{id}", h.UpdateCategory)
		lr.Delete("/categories/{id}", h.DeleteCategory)
		lr.Delete("/categories/{id}/customisation", h.RevertCategory)
		lr.Put("/categories/{id}/count-mode", h.SetCountMode)
		lr.Put("/categories/{id}/balance-rule", h.SetBalanceRule)

		lr.Get("/entitlements", h.ListEntitlements)
		lr.Post("/entitlements", h.UpsertEntitlement)
		lr.Delete("/entitlements/{id}", h.DeleteEntitlement)

		lr.Get("/balances", h.ListBalances)
		lr.Post("/accrue", h.Accrue)

		lr.Get("/holidays", h.ListHolidays)
		lr.Post("/holidays", h.CreateHoliday)
		lr.Put("/holidays/{id}", h.UpdateHoliday)
		lr.Patch("/holidays/{id}", h.UpdateHoliday)
		lr.Delete("/holidays/{id}", h.DeleteHoliday)
		lr.Put("/holidays/{id}/active", h.SetHolidayActive)

		lr.Get("/logs", h.ListLogs)

		lr.Get("/requests", h.ListRequests)
		lr.Post("/requests", h.CreateRequest)
		lr.Get("/requests/preview", h.PreviewRequest)
		lr.Get("/requests/{id}", h.GetRequest)
		lr.Put("/requests/{id}", h.UpdateRequest)
		lr.Post("/requests/{id}/approve", h.ApproveRequest)
		lr.Post("/requests/{id}/reject", h.RejectRequest)
		lr.Post("/requests/{id}/cancel", h.CancelRequest)
	})
}

// ---- Categories ----

func (h *LeaveHandler) ListCategories(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	// Staff without the view permission still need the types to apply for their own leave.
	if !hasPermission(scope, permLeaveView) {
		if _, _, ok := selfEmployee(w, r); !ok {
			return
		}
	}
	rows, err := h.svc.ListCategories(r.Context(), scope.TenantID)
	if err != nil {
		h.log.Error("list categories", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list leave categories")
		return
	}
	views, err := h.svc.CategoryViews(r.Context(), scope.TenantID, rows)
	if err != nil {
		h.log.Error("list categories", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list leave categories")
		return
	}
	writePagedSlice(w, views, pagination.Parse(r))
}

type categoryBody struct {
	Name              string  `json:"name"`
	Description       *string `json:"description"`
	IsActive          *bool   `json:"is_active"`
	IsPaid            *bool   `json:"is_paid"`
	DefaultAnnualDays string  `json:"default_annual_days"`
	// max_days is the UI's name for the default yearly entitlement; accept either.
	MaxDays          string  `json:"max_days"`
	AllowCarryover   *bool   `json:"allow_carryover"`
	CarryForward     *bool   `json:"carry_forward"`
	MaxCarryoverDays *string `json:"max_carryover_days"`
}

// toInput builds the saved values. On an edit, current is the row being edited and a field the
// body leaves out keeps its value (the edit form does not send them all); a new type starts
// active and paid, without carryover.
func (b categoryBody) toInput(current *ent.LeaveCategory) (leave.CategoryInput, error) {
	in := leave.CategoryInput{Name: b.Name, IsActive: true, IsPaid: true}
	if current != nil {
		in = leave.CategoryInput{Name: current.Name, Description: current.Description, IsActive: current.IsActive,
			IsPaid: current.IsPaid, DefaultAnnualDays: current.DefaultAnnualDays,
			AllowCarryover: current.AllowCarryover, MaxCarryoverDays: current.MaxCarryoverDays}
		if strings.TrimSpace(b.Name) != "" {
			in.Name = b.Name
		}
	}
	if b.Description != nil {
		in.Description = *b.Description
	}
	if b.IsActive != nil {
		in.IsActive = *b.IsActive
	}
	if b.IsPaid != nil {
		in.IsPaid = *b.IsPaid
	}
	// carry_forward is the UI's name for allow_carryover.
	if b.CarryForward != nil {
		in.AllowCarryover = *b.CarryForward
	}
	if b.AllowCarryover != nil {
		in.AllowCarryover = *b.AllowCarryover
	}
	// max_days is the UI's name for the default yearly entitlement; accept either.
	days := b.DefaultAnnualDays
	if days == "" {
		days = b.MaxDays
	}
	if days != "" || current == nil {
		d, err := parseDecimalDefault(days)
		if err != nil {
			return in, err
		}
		in.DefaultAnnualDays = d
	}
	if b.MaxCarryoverDays != nil {
		m, err := parseDecimalDefault(*b.MaxCarryoverDays)
		if err != nil {
			return in, err
		}
		in.MaxCarryoverDays = m
	}
	return in, nil
}

func (h *LeaveHandler) CreateCategory(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	var body categoryBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	in, err := body.toInput(nil)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	row, err := h.svc.CreateCategory(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	h.writeCategory(w, r, http.StatusCreated, scope.TenantID, row)
}

// writeCategory sends a saved leave type as the list shows it: is_active always present (ent
// leaves a false one out) and the inherited and customised marks.
func (h *LeaveHandler) writeCategory(w http.ResponseWriter, r *http.Request, status int, tenantID uuid.UUID, row *ent.LeaveCategory) {
	views, err := h.svc.CategoryViews(r.Context(), tenantID, []*ent.LeaveCategory{row})
	if err != nil {
		h.log.Error("leave type view", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "saved, but failed to load the leave type")
		return
	}
	writeJSON(w, status, views[0])
}

func (h *LeaveHandler) UpdateCategory(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body categoryBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	current, err := h.svc.OwnCategory(r.Context(), scope.TenantID, id)
	inherited := errors.Is(err, leave.ErrInheritedCategory)
	if inherited {
		// An inherited type is customised: the changes are kept for this company only.
		current, err = h.svc.UsableCategory(r.Context(), scope.TenantID, id)
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	in, err := body.toInput(current)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	var row *ent.LeaveCategory
	if inherited {
		if leave.NameKey(in.Name) != leave.NameKey(current.Name) {
			writeError(w, http.StatusBadRequest, "update_failed", leave.ErrInheritedName.Error())
			return
		}
		row, err = h.svc.CustomiseCategory(r.Context(), scope.TenantID, id, in)
	} else {
		row, err = h.svc.UpdateCategory(r.Context(), scope.TenantID, id, in)
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	h.writeCategory(w, r, http.StatusOK, scope.TenantID, row)
}

// RevertCategory drops the company's changes to an inherited leave type.
func (h *LeaveHandler) RevertCategory(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.RevertCategory(r.Context(), scope.TenantID, id)
	switch {
	case errors.Is(err, leave.ErrUnknownCategory):
		writeError(w, http.StatusNotFound, "not_found", err.Error())
	case errors.Is(err, leave.ErrNotCustomised):
		writeError(w, http.StatusConflict, "not_customised", err.Error())
	case err != nil:
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to revert the leave type")
	default:
		h.writeCategory(w, r, http.StatusOK, scope.TenantID, row)
	}
}

func (h *LeaveHandler) DeleteCategory(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteCategory(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Entitlements / balances / accrual ----

func (h *LeaveHandler) ListEntitlements(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	year, _ := strconv.Atoi(r.URL.Query().Get("year"))
	rows, err := h.svc.ListEntitlementsEnriched(r.Context(), scope.TenantID, empID, year)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list entitlements")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type entitlementBody struct {
	EmployeeID string `json:"employee_id"`
	CategoryID string `json:"category_id"`
	Year       int    `json:"year"`
	Days       string `json:"days_entitled"`
}

func (h *LeaveHandler) UpsertEntitlement(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	var body entitlementBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(body.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	catID, err := uuid.Parse(body.CategoryID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid category_id")
		return
	}
	days, err := decimal.NewFromString(body.Days)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid days_entitled")
		return
	}
	if body.Year == 0 {
		body.Year = time.Now().UTC().Year()
	}
	row, err := h.svc.UpsertEntitlement(r.Context(), scope.TenantID, empID, catID, body.Year, days)
	if err != nil {
		leaveRequestError(w, "upsert_failed", err)
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *LeaveHandler) ListBalances(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	// ESS: ?mine=true is self-service (scoped to the caller's own employee) and bypasses
	// the manager view permission; otherwise the manager perm is required.
	mine := r.URL.Query().Get("mine") == "true"
	if !mine && !requirePermission(w, scope, permLeaveView) {
		return
	}
	empID := selfOrParamEmployeeID(r, scope)
	year, _ := strconv.Atoi(r.URL.Query().Get("year"))
	rows, err := h.svc.ListBalancesEnriched(r.Context(), scope.TenantID, empID, year)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list balances")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

func (h *LeaveHandler) Accrue(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	year, _ := strconv.Atoi(r.URL.Query().Get("year"))
	if year == 0 {
		year = time.Now().UTC().Year()
	}
	res, err := h.svc.AccrueYear(r.Context(), scope.TenantID, year)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "accrual_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"year": res.Year, "processed": res.Processed})
}

// ---- Holidays ----

func (h *LeaveHandler) ListHolidays(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveView) {
		return
	}
	year, _ := strconv.Atoi(r.URL.Query().Get("year"))
	rows, err := h.svc.ListHolidays(r.Context(), h.holidayTenant(r, scope), year)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list holidays")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

// holidayTenant is the tenant whose holidays a request reads or writes: the platform's national
// list when the platform owner asks for scope=platform, else the caller's own.
func (h *LeaveHandler) holidayTenant(r *http.Request, scope RequestScope) uuid.UUID {
	if r.URL.Query().Get("scope") == "platform" && isPlatformOwner(scope) && h.svc.SystemTenant() != uuid.Nil {
		return h.svc.SystemTenant()
	}
	return scope.TenantID
}

// SetHolidayActive switches one of the platform's national holidays off for the caller's company,
// or back on (the revert). The company's own holidays are edited or deleted instead.
func (h *LeaveHandler) SetHolidayActive(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body struct {
		Active *bool `json:"active"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.Active == nil {
		writeError(w, http.StatusBadRequest, "bad_request", "active (true or false) is required")
		return
	}
	row, err := h.svc.SetHolidayActive(r.Context(), scope.TenantID, id, *body.Active)
	if errors.Is(err, leave.ErrHolidayNotFound) {
		writeError(w, http.StatusNotFound, "not_found", "platform holiday not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to switch the holiday")
		return
	}
	writeJSON(w, http.StatusOK, row)
}

type holidayBody struct {
	Name       string `json:"name"`
	Date       string `json:"date"`
	IsNational *bool  `json:"is_national"`
	County     string `json:"county"`
}

// decodeHoliday reads a holiday body, writing the 400 itself on failure. is_national defaults
// to true when it is left out.
func decodeHoliday(w http.ResponseWriter, r *http.Request) (leave.HolidayInput, bool) {
	var body holidayBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return leave.HolidayInput{}, false
	}
	date, err := parseDate(body.Date)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid date (want YYYY-MM-DD)")
		return leave.HolidayInput{}, false
	}
	return leave.HolidayInput{
		Name: body.Name, Date: date, County: body.County,
		IsNational: body.IsNational == nil || *body.IsNational,
	}, true
}

func (h *LeaveHandler) CreateHoliday(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	in, ok := decodeHoliday(w, r)
	if !ok {
		return
	}
	row, err := h.svc.CreateHoliday(r.Context(), h.holidayTenant(r, scope), in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", clientMessage(err))
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

// UpdateHoliday edits one of the tenant's holidays (PUT and PATCH take the full body).
func (h *LeaveHandler) UpdateHoliday(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := decodeHoliday(w, r)
	if !ok {
		return
	}
	row, err := h.svc.UpdateHoliday(r.Context(), h.holidayTenant(r, scope), id, in)
	if errors.Is(err, leave.ErrHolidayNotFound) {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", clientMessage(err))
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *LeaveHandler) DeleteHoliday(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteHoliday(r.Context(), h.holidayTenant(r, scope), id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- Logs ----

// ListLogs returns the leave audit trail (optionally filtered by leave_request_id).
func (h *LeaveHandler) ListLogs(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveView) {
		return
	}
	reqID := optionalUUIDParam(r, "leave_request_id")
	if reqID == nil {
		reqID = optionalUUIDParam(r, "request_id")
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListLogs(r.Context(), scope.TenantID, reqID, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list leave logs")
		return
	}
	views, err := h.svc.LogViews(r.Context(), scope.TenantID, rows)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list leave logs")
		return
	}
	writePaginated(w, views, total, p)
}

// ---- Requests ----

func (h *LeaveHandler) ListRequests(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	// ?mine=true is self-service: the caller's own requests, without the view permission.
	if r.URL.Query().Get("mine") != "true" && !requirePermission(w, scope, permLeaveView) {
		return
	}
	f := leave.RequestFilter{
		EmployeeID: selfOrParamEmployeeID(r, scope),
		Status:     r.URL.Query().Get("status"),
		Search:     r.URL.Query().Get("search"),
	}
	if d, err := parseDate(r.URL.Query().Get("from")); err == nil {
		f.From = &d
	}
	if d, err := parseDate(r.URL.Query().Get("to")); err == nil {
		f.To = &d
	}
	p := pagination.Parse(r)
	rows, total, err := h.svc.ListRequests(r.Context(), scope.TenantID, f, p.Limit, p.Offset)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list requests")
		return
	}
	views, err := h.svc.RequestViews(r.Context(), scope.TenantID, rows)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list requests")
		return
	}
	writePaginated(w, views, total, p)
}

func (h *LeaveHandler) GetRequest(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.Get(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "leave request not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to fetch request")
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// createRequestBody has no day count: the server counts the days, and a days_requested sent by an
// older client is ignored. An empty employee_id files for the caller.
type createRequestBody struct {
	EmployeeID string `json:"employee_id"`
	CategoryID string `json:"category_id"`
	StartDate  string `json:"start_date"`
	EndDate    string `json:"end_date"`
	// StartHalfDay starts the leave at midday on the start date; EndHalfDay ends it at midday on
	// the end date.
	StartHalfDay bool   `json:"start_half_day"`
	EndHalfDay   bool   `json:"end_half_day"`
	Reason       string `json:"reason"`
}

// writeRequest sends one leave request as the list shows it (names, and the half-day flags even
// when false).
func (h *LeaveHandler) writeRequest(w http.ResponseWriter, r *http.Request, status int, tenantID uuid.UUID, row *ent.LeaveRequest) {
	views, err := h.svc.RequestViews(r.Context(), tenantID, []*ent.LeaveRequest{row})
	if err != nil {
		h.log.Error("leave request view", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "saved, but failed to load the leave request")
		return
	}
	writeJSON(w, status, views[0])
}

// requestDates reads a body's type and dates, writing the 400 itself on failure.
func requestDates(w http.ResponseWriter, categoryID, startDate, endDate string) (uuid.UUID, time.Time, time.Time, bool) {
	catID, err := uuid.Parse(categoryID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid category_id")
		return uuid.Nil, time.Time{}, time.Time{}, false
	}
	start, err := parseDate(startDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid start_date")
		return uuid.Nil, time.Time{}, time.Time{}, false
	}
	end, err := parseDate(endDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid end_date")
		return uuid.Nil, time.Time{}, time.Time{}, false
	}
	return catID, start, end, true
}

type updateRequestBody struct {
	CategoryID   string  `json:"category_id"`
	StartDate    string  `json:"start_date"`
	EndDate      string  `json:"end_date"`
	StartHalfDay bool    `json:"start_half_day"`
	EndHalfDay   bool    `json:"end_half_day"`
	Reason       *string `json:"reason"`
}

// UpdateRequest changes a pending request: HR (leave manage) any, anyone else only their own (404
// for someone else's). The employee stays; the days and the balance are counted again.
func (h *LeaveHandler) UpdateRequest(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body updateRequestBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	var own *uuid.UUID
	if !hasPermission(scope, permLeaveManage) {
		_, empID, ok := selfEmployee(w, r)
		if !ok {
			return
		}
		own = &empID
	}
	catID, start, end, ok := requestDates(w, body.CategoryID, body.StartDate, body.EndDate)
	if !ok {
		return
	}
	uid := scope.UserID
	row, err := h.svc.UpdateRequest(r.Context(), scope.TenantID, id, own, leave.UpdateRequestInput{
		CategoryID: catID, StartDate: start, EndDate: end, StartHalfDay: body.StartHalfDay, EndHalfDay: body.EndHalfDay,
		Reason: body.Reason, ActingUserID: &uid,
	})
	if err != nil {
		leaveRequestError(w, "update_failed", err)
		return
	}
	h.writeRequest(w, r, http.StatusOK, scope.TenantID, row)
}

func (h *LeaveHandler) CreateRequest(w http.ResponseWriter, r *http.Request) {
	var body createRequestBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	scope, empID, ok := leaveFiler(w, r, body.EmployeeID)
	if !ok {
		return
	}
	catID, start, end, ok := requestDates(w, body.CategoryID, body.StartDate, body.EndDate)
	if !ok {
		return
	}
	uid := scope.UserID
	row, err := h.svc.CreateRequest(r.Context(), scope.TenantID, leave.CreateRequestInput{
		EmployeeID: empID, CategoryID: catID, StartDate: start, EndDate: end,
		StartHalfDay: body.StartHalfDay, EndHalfDay: body.EndHalfDay,
		Reason: body.Reason, ActingUserID: &uid,
	})
	if err != nil {
		leaveRequestError(w, "create_failed", err)
		return
	}
	h.writeRequest(w, r, http.StatusCreated, scope.TenantID, row)
}

func (h *LeaveHandler) ApproveRequest(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveApprove) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	// Nobody approves their own request, whatever their role.
	if req, gerr := h.svc.Get(r.Context(), scope.TenantID, id); gerr == nil && isOwnEmployee(r, scope, req.EmployeeID) {
		writeError(w, http.StatusForbidden, "own_request", ownLeaveMessage)
		return
	}
	uid := scope.UserID
	row, err := h.svc.Approve(r.Context(), scope.TenantID, id, nil, &uid)
	if err != nil {
		writeError(w, http.StatusBadRequest, "approve_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

type rejectBody struct {
	Reason string `json:"reason"`
}

func (h *LeaveHandler) RejectRequest(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permLeaveApprove) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body rejectBody
	_ = json.NewDecoder(r.Body).Decode(&body)
	uid := scope.UserID
	row, err := h.svc.Reject(r.Context(), scope.TenantID, id, body.Reason, &uid)
	if err != nil {
		writeError(w, http.StatusBadRequest, "reject_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *LeaveHandler) CancelRequest(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	uid := scope.UserID
	var row *ent.LeaveRequest
	if hasPermission(scope, permLeaveManage) {
		row, err = h.svc.Cancel(r.Context(), scope.TenantID, id, &uid)
	} else {
		_, empID, ok := selfEmployee(w, r)
		if !ok {
			return
		}
		row, err = h.svc.CancelOwn(r.Context(), scope.TenantID, id, empID, &uid)
	}
	if err != nil {
		leaveRequestError(w, "cancel_failed", err)
		return
	}
	writeJSON(w, http.StatusOK, row)
}
