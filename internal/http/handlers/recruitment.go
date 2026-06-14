package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/recruitment"
)

// Recruitment RBAC permission codes.
const (
	permRecruitmentView   = "hrm.recruitment.view"
	permRecruitmentManage = "hrm.recruitment.manage"
)

// RecruitmentHandler serves /api/v1/hrm/recruitment/*.
type RecruitmentHandler struct {
	log *zap.Logger
	svc *recruitment.Service
}

func NewRecruitmentHandler(log *zap.Logger, svc *recruitment.Service) *RecruitmentHandler {
	return &RecruitmentHandler{log: log.Named("hrm.recruitment"), svc: svc}
}

func (h *RecruitmentHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/recruitment", func(rr chi.Router) {
		rr.Get("/postings", h.ListPostings)
		rr.Post("/postings", h.CreatePosting)
		rr.Put("/postings/{id}/status", h.SetPostingStatus)

		rr.Get("/candidates", h.ListCandidates)
		rr.Post("/candidates", h.CreateCandidate)

		rr.Get("/applications", h.ListApplications)
		rr.Post("/applications", h.CreateApplication)
		rr.Post("/applications/{id}/transition", h.TransitionApplication)

		rr.Get("/onboarding", h.ListOnboardings)
		rr.Post("/onboarding", h.StartOnboarding)
		rr.Get("/onboarding/{id}/tasks", h.ListTasks)
		rr.Put("/onboarding/tasks/{taskID}/complete", h.CompleteTask)
	})
}

// ---- Postings ----

func (h *RecruitmentHandler) ListPostings(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentView) {
		return
	}
	rows, err := h.svc.ListPostings(r.Context(), scope.TenantID, r.URL.Query().Get("status"))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list postings")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}

type postingBody struct {
	Title       string `json:"title"`
	Description string `json:"description"`
	Department  string `json:"department"`
	Location    string `json:"location"`
	Status      string `json:"status"`
}

func (h *RecruitmentHandler) CreatePosting(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	var b postingBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.CreatePosting(r.Context(), scope.TenantID, recruitment.PostingInput{
		Title: b.Title, Description: b.Description, Department: b.Department,
		Location: b.Location, Status: b.Status,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

type statusBody struct {
	Status string `json:"status"`
}

func (h *RecruitmentHandler) SetPostingStatus(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
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
	row, err := h.svc.SetPostingStatus(r.Context(), scope.TenantID, id, b.Status)
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// ---- Candidates ----

func (h *RecruitmentHandler) ListCandidates(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentView) {
		return
	}
	rows, err := h.svc.ListCandidates(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list candidates")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}

type candidateBody struct {
	FullName  string `json:"full_name"`
	Email     string `json:"email"`
	Phone     string `json:"phone"`
	ResumeURL string `json:"resume_url"`
}

func (h *RecruitmentHandler) CreateCandidate(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	var b candidateBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.CreateCandidate(r.Context(), scope.TenantID, recruitment.CandidateInput{
		FullName: b.FullName, Email: b.Email, Phone: b.Phone, ResumeURL: b.ResumeURL,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

// ---- Applications ----

func (h *RecruitmentHandler) ListApplications(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentView) {
		return
	}
	jobID := optionalUUIDParam(r, "job_id")
	rows, err := h.svc.ListApplications(r.Context(), scope.TenantID, jobID, r.URL.Query().Get("status"))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list applications")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}

type applicationBody struct {
	JobID       string `json:"job_id"`
	CandidateID string `json:"candidate_id"`
	Notes       string `json:"notes"`
}

func (h *RecruitmentHandler) CreateApplication(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	var b applicationBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	jobID, err := uuid.Parse(b.JobID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid job_id")
		return
	}
	candID, err := uuid.Parse(b.CandidateID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid candidate_id")
		return
	}
	row, err := h.svc.CreateApplication(r.Context(), scope.TenantID, jobID, candID, b.Notes)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

type transitionBody struct {
	Status         string `json:"status"`
	CreateEmployee bool   `json:"create_employee"`
}

func (h *RecruitmentHandler) TransitionApplication(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b transitionBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	res, err := h.svc.Transition(r.Context(), scope.TenantID, id, b.Status, b.CreateEmployee)
	if err != nil {
		writeError(w, http.StatusBadRequest, "transition_failed", err.Error())
		return
	}
	out := map[string]any{"application": res.Application}
	if res.EmployeeID != nil {
		out["employee_id"] = res.EmployeeID.String()
	}
	if res.OnboardingID != nil {
		out["onboarding_id"] = res.OnboardingID.String()
	}
	writeJSON(w, http.StatusOK, out)
}

// ---- Onboarding ----

func (h *RecruitmentHandler) ListOnboardings(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListOnboardings(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list onboardings")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}

type startOnboardingBody struct {
	EmployeeID string `json:"employee_id"`
}

func (h *RecruitmentHandler) StartOnboarding(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	var b startOnboardingBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	row, err := h.svc.StartOnboarding(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "start_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *RecruitmentHandler) ListTasks(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	rows, err := h.svc.ListTasks(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list tasks")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"data": rows})
}

type completeTaskBody struct {
	Done *bool `json:"done"`
}

func (h *RecruitmentHandler) CompleteTask(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	taskID, err := uuid.Parse(chi.URLParam(r, "taskID"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid task id")
		return
	}
	var b completeTaskBody
	_ = json.NewDecoder(r.Body).Decode(&b)
	done := b.Done == nil || *b.Done
	row, err := h.svc.CompleteTask(r.Context(), scope.TenantID, taskID, done)
	if err != nil {
		writeError(w, http.StatusBadRequest, "complete_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}
