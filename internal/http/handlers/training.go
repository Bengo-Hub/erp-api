package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

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
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}

type courseBody struct {
	Title       string `json:"title"`
	Description string `json:"description"`
	StartDate   string `json:"start_date"`
	EndDate     string `json:"end_date"`
	Capacity    int    `json:"capacity"`
}

func (h *TrainingHandler) CreateCourse(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTrainingManage) {
		return
	}
	var b courseBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	start, err := parseDate(b.StartDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid start_date")
		return
	}
	end, err := parseDate(b.EndDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid end_date")
		return
	}
	row, err := h.svc.CreateCourse(r.Context(), scope.TenantID, training.CourseInput{
		Title: b.Title, Description: b.Description, StartDate: start, EndDate: end, Capacity: b.Capacity,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
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
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
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
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
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
