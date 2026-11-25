package handlers

import (
	"encoding/json"
	"errors"
	"net/http"
	"strconv"
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

		lr.Get("/logs", h.ListLogs)

		lr.Get("/requests", h.ListRequests)
		lr.Post("/requests", h.CreateRequest)
		lr.Get("/requests/preview", h.PreviewRequest)
		lr.Get("/requests/{id}", h.GetRequest)
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
	Name              string `json:"name"`
	Description       string `json:"description"`
	IsActive          *bool  `json:"is_active"`
	IsPaid            *bool  `json:"is_paid"`
	DefaultAnnualDays string `json:"default_annual_days"`
	// max_days is the UI's name for the default yearly entitlement; accept either.
	MaxDays          string `json:"max_days"`
	AllowCarryover   bool   `json:"allow_carryover"`
	CarryForward     *bool  `json:"carry_forward"`
	MaxCarryoverDays string `json:"max_carryover_days"`
}

func (b categoryBody) toInput() (leave.CategoryInput, error) {
	in := leave.CategoryInput{
		Name:           b.Name,
		Description:    b.Description,
		IsActive:       b.IsActive == nil || *b.IsActive,
		IsPaid:         b.IsPaid == nil || *b.IsPaid,
		AllowCarryover: b.AllowCarryover || (b.CarryForward != nil && *b.CarryForward),
	}
	// Accept the UI alias `max_days` when `default_annual_days` is not supplied.
	if b.DefaultAnnualDays == "" && b.MaxDays != "" {
		b.DefaultAnnualDays = b.MaxDays
	}
	d, err := parseDecimalDefault(b.DefaultAnnualDays)
	if err != nil {
		return in, err
	}
	in.DefaultAnnualDays = d
	m, err := parseDecimalDefault(b.MaxCarryoverDays)
	if err != nil {
		return in, err
	}
	in.MaxCarryoverDays = m
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
	in, err := body.toInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	row, err := h.svc.CreateCategory(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
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
	in, err := body.toInput()
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", err.Error())
		return
	}
	row, err := h.svc.UpdateCategory(r.Context(), scope.TenantID, id, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
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
	rows, err := h.svc.ListHolidays(r.Context(), scope.TenantID, year)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list holidays")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
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
	row, err := h.svc.CreateHoliday(r.Context(), scope.TenantID, in)
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
	row, err := h.svc.UpdateHoliday(r.Context(), scope.TenantID, id, in)
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
	if err := h.svc.DeleteHoliday(r.Context(), scope.TenantID, id); err != nil {
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
	Reason     string `json:"reason"`
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
	catID, err := uuid.Parse(body.CategoryID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid category_id")
		return
	}
	start, err := parseDate(body.StartDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid start_date")
		return
	}
	end, err := parseDate(body.EndDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid end_date")
		return
	}
	uid := scope.UserID
	row, err := h.svc.CreateRequest(r.Context(), scope.TenantID, leave.CreateRequestInput{
		EmployeeID: empID, CategoryID: catID, StartDate: start, EndDate: end,
		Reason: body.Reason, ActingUserID: &uid,
	})
	if err != nil {
		leaveRequestError(w, "create_failed", err)
		return
	}
	writeJSON(w, http.StatusCreated, row)
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
