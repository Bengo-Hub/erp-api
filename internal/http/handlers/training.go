package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/training"
)

// Training RBAC permission codes.
const (
	permTrainingView   = "hrm.training.view"
	permTrainingManage = "hrm.training.manage"
)

// TrainingHandler serves /api/v1/hrm/training/*.
type TrainingHandler struct {
	log *zap.Logger
	svc *training.Service
}

func NewTrainingHandler(log *zap.Logger, svc *training.Service) *TrainingHandler {
	return &TrainingHandler{log: log.Named("hrm.training"), svc: svc}
}

func (h *TrainingHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/training", func(tr chi.Router) {
		tr.Get("/courses", h.ListCourses)
		tr.Post("/courses", h.CreateCourse)
		tr.Put("/courses/{id}", h.UpdateCourse)
		tr.Delete("/courses/{id}", h.DeleteCourse)

		tr.Get("/enrollments", h.ListEnrollments)
		tr.Post("/enrollments", h.Enroll)
		tr.Put("/enrollments/{id}/status", h.SetEnrollmentStatus)

		tr.Get("/evaluations", h.ListEvaluations)
		tr.Post("/evaluations", h.CreateEvaluation)
	})
}

func (h *TrainingHandler) ListCourses(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingView) {
		return
	}
	rows, err := h.svc.ListCourses(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list courses")
		return
	}
	views := make([]training.CourseView, len(rows))
	for i, c := range rows {
		views[i] = training.ViewCourse(c)
	}
	writePagedSlice(w, views, pagination.Parse(r))
}

// courseBody is the course create/update payload. duration (hours) and cost take a JSON
// number or a numeric string.
type courseBody struct {
	Title       string      `json:"title"`
	Description string      `json:"description"`
	StartDate   string      `json:"start_date"`
	EndDate     string      `json:"end_date"`
	Capacity    int         `json:"capacity"`
	Provider    string      `json:"provider"`
	Duration    json.Number `json:"duration"`
	Cost        json.Number `json:"cost"`
	Status      string      `json:"status"`
}

// decodeCourse reads and validates a course body; it writes the error response itself.
func decodeCourse(w http.ResponseWriter, r *http.Request) (training.CourseInput, bool) {
	var b courseBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body (duration and cost must be numbers)")
		return training.CourseInput{}, false
	}
	start, err := parseDate(b.StartDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid start_date")
		return training.CourseInput{}, false
	}
	end, err := parseDate(b.EndDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid end_date")
		return training.CourseInput{}, false
	}
	return training.CourseInput{
		Title: b.Title, Description: b.Description, StartDate: start, EndDate: end, Capacity: b.Capacity,
		Provider: b.Provider, Duration: b.Duration.String(), Cost: b.Cost.String(), Status: b.Status,
	}, true
}

func (h *TrainingHandler) CreateCourse(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingManage) {
		return
	}
	in, ok := decodeCourse(w, r)
	if !ok {
		return
	}
	row, err := h.svc.CreateCourse(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, training.ViewCourse(row))
}

// UpdateCourse replaces a course's details.
func (h *TrainingHandler) UpdateCourse(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := decodeCourse(w, r)
	if !ok {
		return
	}
	row, err := h.svc.UpdateCourse(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "course not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, training.ViewCourse(row))
}

func (h *TrainingHandler) DeleteCourse(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteCourse(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusNotFound, "not_found", err.Error())
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

func (h *TrainingHandler) ListEnrollments(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingView) {
		return
	}
	courseID := optionalUUIDParam(r, "course_id")
	rows, err := h.svc.ListEnrollments(r.Context(), scope.TenantID, courseID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list enrollments")
		return
	}
	views, err := h.svc.DescribeEnrollments(r.Context(), scope.TenantID, rows)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list enrollments")
		return
	}
	writePagedSlice(w, views, pagination.Parse(r))
}

type enrollBody struct {
	CourseID   string `json:"course_id"`
	EmployeeID string `json:"employee_id"`
}

func (h *TrainingHandler) Enroll(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingManage) {
		return
	}
	var b enrollBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	courseID, err := uuid.Parse(b.CourseID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid course_id")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	row, err := h.svc.Enroll(r.Context(), scope.TenantID, courseID, empID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "enroll_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *TrainingHandler) SetEnrollmentStatus(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b statusBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.SetEnrollmentStatus(r.Context(), scope.TenantID, id, b.Status)
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *TrainingHandler) ListEvaluations(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingView) {
		return
	}
	courseID := optionalUUIDParam(r, "course_id")
	rows, err := h.svc.ListEvaluations(r.Context(), scope.TenantID, courseID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list evaluations")
		return
	}
	views, err := h.svc.DescribeEvaluations(r.Context(), scope.TenantID, rows)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list evaluations")
		return
	}
	writePagedSlice(w, views, pagination.Parse(r))
}

type trainingEvalBody struct {
	CourseID   string `json:"course_id"`
	EmployeeID string `json:"employee_id"`
	Rating     int    `json:"rating"`
	Feedback   string `json:"feedback"`
}

func (h *TrainingHandler) CreateEvaluation(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingManage) {
		return
	}
	var b trainingEvalBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	courseID, err := uuid.Parse(b.CourseID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid course_id")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	row, err := h.svc.CreateEvaluation(r.Context(), scope.TenantID, courseID, empID, b.Rating, b.Feedback)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}
