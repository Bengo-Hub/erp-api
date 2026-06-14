package handlers

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/performance"
)

// Performance RBAC permission codes.
const (
	permPerformanceView   = "hrm.performance.view"
	permPerformanceManage = "hrm.performance.manage"
)

// PerformanceHandler serves /api/v1/hrm/performance/*.
type PerformanceHandler struct {
	log *zap.Logger
	svc *performance.Service
}

func NewPerformanceHandler(log *zap.Logger, svc *performance.Service) *PerformanceHandler {
	return &PerformanceHandler{log: log.Named("hrm.performance"), svc: svc}
}

func (h *PerformanceHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/performance", func(pr chi.Router) {
		pr.Get("/categories", h.ListCategories)
		pr.Post("/categories", h.CreateCategory)

		pr.Get("/metrics", h.ListMetrics)
		pr.Post("/metrics", h.CreateMetric)

		pr.Get("/employee-metrics", h.ListEmployeeMetrics)
		pr.Post("/employee-metrics", h.RecordEmployeeMetric)

		pr.Get("/targets", h.ListTargets)
		pr.Post("/targets", h.SetTarget)

		pr.Get("/reviews", h.ListReviews)
		pr.Post("/reviews", h.CreateReview)
		pr.Put("/reviews/{id}/status", h.SetReviewStatus)
		pr.Get("/reviews/{id}/metrics", h.ListReviewMetrics)
		pr.Put("/reviews/{id}/metrics", h.UpsertReviewMetric)
	})
}

func (h *PerformanceHandler) ListCategories(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceView) {
		return
	}
	rows, err := h.svc.ListCategories(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list categories")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type metricCategoryBody struct {
	Name        string `json:"name"`
	Description string `json:"description"`
	Order       int    `json:"order"`
}

func (h *PerformanceHandler) CreateCategory(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceManage) {
		return
	}
	var b metricCategoryBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	uid := scope.UserID
	row, err := h.svc.CreateCategory(r.Context(), scope.TenantID, b.Name, b.Description, b.Order, &uid)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *PerformanceHandler) ListMetrics(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceView) {
		return
	}
	catID := optionalUUIDParam(r, "category_id")
	rows, err := h.svc.ListMetrics(r.Context(), scope.TenantID, catID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list metrics")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type metricBody struct {
	CategoryID  string `json:"category_id"`
	Name        string `json:"name"`
	Description string `json:"description"`
	MetricType  string `json:"metric_type"`
	Unit        string `json:"unit"`
	MinValue    string `json:"min_value"`
	MaxValue    string `json:"max_value"`
	TargetValue string `json:"target_value"`
}

func (h *PerformanceHandler) CreateMetric(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceManage) {
		return
	}
	var b metricBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	catID, err := uuid.Parse(b.CategoryID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid category_id")
		return
	}
	uid := scope.UserID
	row, err := h.svc.CreateMetric(r.Context(), scope.TenantID, performance.MetricInput{
		CategoryID: catID, Name: b.Name, Description: b.Description, MetricType: b.MetricType,
		Unit: b.Unit, MinValue: b.MinValue, MaxValue: b.MaxValue, TargetValue: b.TargetValue, CreatedBy: &uid,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *PerformanceHandler) ListEmployeeMetrics(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListEmployeeMetrics(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list employee metrics")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type recordMetricBody struct {
	EmployeeID   string `json:"employee_id"`
	MetricID     string `json:"metric_id"`
	Value        string `json:"value"`
	DateRecorded string `json:"date_recorded"`
	Notes        string `json:"notes"`
}

func (h *PerformanceHandler) RecordEmployeeMetric(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceManage) {
		return
	}
	var b recordMetricBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	metricID, err := uuid.Parse(b.MetricID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid metric_id")
		return
	}
	date, err := parseDate(b.DateRecorded)
	if err != nil {
		date = time.Now().UTC().Truncate(24 * time.Hour)
	}
	uid := scope.UserID
	row, err := h.svc.RecordEmployeeMetric(r.Context(), scope.TenantID, performance.RecordMetricInput{
		EmployeeID: empID, MetricID: metricID, Value: b.Value, DateRecorded: date, Notes: b.Notes, RecordedBy: &uid,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "record_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *PerformanceHandler) ListTargets(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListTargets(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list targets")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type targetBody struct {
	EmployeeID  string `json:"employee_id"`
	MetricID    string `json:"metric_id"`
	TargetValue string `json:"target_value"`
	PeriodStart string `json:"period_start"`
	PeriodEnd   string `json:"period_end"`
}

func (h *PerformanceHandler) SetTarget(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceManage) {
		return
	}
	var b targetBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	metricID, err := uuid.Parse(b.MetricID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid metric_id")
		return
	}
	target, err := decimal.NewFromString(b.TargetValue)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid target_value")
		return
	}
	start, err := parseDate(b.PeriodStart)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid period_start")
		return
	}
	end, err := parseDate(b.PeriodEnd)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid period_end")
		return
	}
	uid := scope.UserID
	row, err := h.svc.SetTarget(r.Context(), scope.TenantID, empID, metricID, target, start, end, &uid)
	if err != nil {
		writeError(w, http.StatusBadRequest, "set_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *PerformanceHandler) ListReviews(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListReviews(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list reviews")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type reviewBody struct {
	EmployeeID  string `json:"employee_id"`
	Title       string `json:"title"`
	Description string `json:"description"`
	ReviewDate  string `json:"review_date"`
	ReviewerID  string `json:"reviewer_id"`
}

func (h *PerformanceHandler) CreateReview(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceManage) {
		return
	}
	var b reviewBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	reviewDate, err := parseDate(b.ReviewDate)
	if err != nil {
		reviewDate = time.Now().UTC().Truncate(24 * time.Hour)
	}
	uid := scope.UserID
	in := performance.ReviewInput{
		EmployeeID: empID, Title: b.Title, Description: b.Description,
		ReviewDate: reviewDate, CreatedBy: &uid,
	}
	if b.ReviewerID != "" {
		if rid, perr := uuid.Parse(b.ReviewerID); perr == nil {
			in.ReviewerID = &rid
		}
	}
	row, err := h.svc.CreateReview(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

type reviewStatusBody struct {
	Status        string `json:"status"`
	OverallRating string `json:"overall_rating"`
}

func (h *PerformanceHandler) SetReviewStatus(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b reviewStatusBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.SetReviewStatus(r.Context(), scope.TenantID, id, b.Status, b.OverallRating)
	if err != nil {
		writeError(w, http.StatusBadRequest, "transition_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *PerformanceHandler) ListReviewMetrics(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	rows, err := h.svc.ListReviewMetrics(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list review metrics")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type reviewMetricBody struct {
	MetricID string `json:"metric_id"`
	Value    string `json:"value"`
	Rating   string `json:"rating"`
	Comments string `json:"comments"`
}

func (h *PerformanceHandler) UpsertReviewMetric(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permPerformanceManage) {
		return
	}
	reviewID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b reviewMetricBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	metricID, err := uuid.Parse(b.MetricID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid metric_id")
		return
	}
	row, err := h.svc.UpsertReviewMetric(r.Context(), scope.TenantID, performance.ReviewMetricInput{
		ReviewID: reviewID, MetricID: metricID, Value: b.Value, Rating: b.Rating, Comments: b.Comments,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "upsert_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}
