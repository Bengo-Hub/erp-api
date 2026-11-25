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

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/recruitment"
	"github.com/Bengo-Hub/erp-api/internal/platform/media"
)

// Recruitment RBAC permission codes.
const (
	permRecruitmentView   = "hrm.recruitment.view"
	permRecruitmentManage = "hrm.recruitment.manage"
)

// RecruitmentHandler serves /api/v1/hrm/recruitment/*.
type RecruitmentHandler struct {
	log   *zap.Logger
	svc   *recruitment.Service
	media *media.Store
}

func NewRecruitmentHandler(log *zap.Logger, svc *recruitment.Service, mediaStore *media.Store) *RecruitmentHandler {
	return &RecruitmentHandler{log: log.Named("hrm.recruitment"), svc: svc, media: mediaStore}
}

func (h *RecruitmentHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/recruitment", func(rr chi.Router) {
		rr.Get("/postings", h.ListPostings)
		rr.Post("/postings", h.CreatePosting)
		rr.Put("/postings/{id}", h.UpdatePosting)
		rr.Delete("/postings/{id}", h.DeletePosting)
		rr.Put("/postings/{id}/status", h.SetPostingStatus)

		rr.Get("/candidates", h.ListCandidates)
		rr.Post("/candidates", h.CreateCandidate)
		rr.Put("/candidates/{id}", h.UpdateCandidate)
		rr.Patch("/candidates/{id}", h.UpdateCandidate)
		rr.Delete("/candidates/{id}", h.DeleteCandidate)
		rr.Post("/candidates/{id}/resume", h.UploadResume)

		rr.Get("/applications", h.ListApplications)
		rr.Post("/applications", h.CreateApplication)
		rr.Post("/applications/{id}/transition", h.TransitionApplication)

		rr.Get("/onboarding", h.ListOnboardings)
		rr.Post("/onboarding", h.StartOnboarding)
		rr.Get("/onboarding/{id}/tasks", h.ListTasks)
		rr.Post("/onboarding/{id}/tasks", h.AddTask)
		rr.Put("/onboarding/tasks/{taskID}/complete", h.CompleteTask)
		rr.Put("/onboarding/tasks/{taskID}", h.UpdateTask)
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
	writePagedSlice(w, rows, pagination.Parse(r))
}

type postingBody struct {
	Title               string `json:"title"`
	Description         string `json:"description"`
	Requirements        string `json:"requirements"`
	Responsibilities    string `json:"responsibilities"`
	SalaryMin           string `json:"salary_min"`
	SalaryMax           string `json:"salary_max"`
	SalaryCurrency      string `json:"salary_currency"`
	Department          string `json:"department"`
	Location            string `json:"location"`
	Status              string `json:"status"`
	IsPublic            bool   `json:"is_public"`
	EmploymentType      string `json:"employment_type"`
	NumPositions        int    `json:"num_positions"`
	ApplicationDeadline string `json:"application_deadline"`
}

func (b postingBody) toInput() recruitment.PostingInput {
	in := recruitment.PostingInput{
		Title: b.Title, Description: b.Description, Department: b.Department,
		Requirements: b.Requirements, Responsibilities: b.Responsibilities,
		SalaryMin: b.SalaryMin, SalaryMax: b.SalaryMax, SalaryCurrency: b.SalaryCurrency,
		Location: b.Location, Status: b.Status, IsPublic: b.IsPublic,
		EmploymentType: b.EmploymentType, NumPositions: b.NumPositions,
	}
	if b.ApplicationDeadline != "" {
		if t, err := parseDate(b.ApplicationDeadline); err == nil {
			in.ApplicationDeadline = &t
		}
	}
	return in
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
	row, err := h.svc.CreatePosting(r.Context(), scope.TenantID, b.toInput())
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

// UpdatePosting edits a posting (title/description/visibility/employment type/deadline).
func (h *RecruitmentHandler) UpdatePosting(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b postingBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdatePosting(r.Context(), scope.TenantID, id, b.toInput())
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// DeletePosting removes a posting without applications.
func (h *RecruitmentHandler) DeletePosting(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	err := h.svc.DeletePosting(r.Context(), scope.TenantID, id)
	switch {
	case ent.IsNotFound(err):
		writeError(w, http.StatusNotFound, "not_found", "posting not found")
	case errors.Is(err, recruitment.ErrPostingInUse):
		writeError(w, http.StatusConflict, "in_use", err.Error())
	case err != nil:
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to delete posting")
	default:
		w.WriteHeader(http.StatusNoContent)
	}
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
	views := make([]recruitment.CandidateView, len(rows))
	for i, c := range rows {
		views[i] = recruitment.ViewCandidate(h.withResumeLink(c))
	}
	writePagedSlice(w, views, pagination.Parse(r))
}

type candidateBody struct {
	FullName  string `json:"full_name"`
	Email     string `json:"email"`
	Phone     string `json:"phone"`
	ResumeURL string `json:"resume_url"`
	Source    string `json:"source"`
	Status    string `json:"status"`
}

func (b candidateBody) input() recruitment.CandidateInput {
	return recruitment.CandidateInput{
		FullName: b.FullName, Email: b.Email, Phone: b.Phone, ResumeURL: b.ResumeURL,
		Source: b.Source, Status: b.Status,
	}
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
	row, err := h.svc.CreateCandidate(r.Context(), scope.TenantID, b.input())
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, recruitment.ViewCandidate(h.withResumeLink(row)))
}

// UpdateCandidate changes a candidate's details, source and status.
func (h *RecruitmentHandler) UpdateCandidate(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b candidateBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateCandidate(r.Context(), scope.TenantID, id, b.input())
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "candidate not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, recruitment.ViewCandidate(h.withResumeLink(row)))
}

// DeleteCandidate removes a candidate with no applications (409 in_use otherwise) and
// deletes the resume file stored for them.
func (h *RecruitmentHandler) DeleteCandidate(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.DeleteCandidate(r.Context(), scope.TenantID, id)
	switch {
	case ent.IsNotFound(err):
		writeError(w, http.StatusNotFound, "not_found", "candidate not found")
		return
	case errors.Is(err, recruitment.ErrCandidateInUse):
		writeError(w, http.StatusConflict, "in_use", err.Error())
		return
	case err != nil:
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to delete candidate")
		return
	}
	if row.ResumeURL != nil && h.media != nil && h.media.Enabled() {
		if rerr := h.media.Release(r.Context(), *row.ResumeURL, ""); rerr != nil {
			h.log.Warn("deleted candidate's resume not removed", zap.Error(rerr))
		}
	}
	w.WriteHeader(http.StatusNoContent)
}

// withResumeLink swaps a stored resume key for a short-lived presigned link in a response (the
// row itself keeps the key); an external link a candidate gave is left as is.
func (h *RecruitmentHandler) withResumeLink(c *ent.Candidate) *ent.Candidate {
	if c != nil && c.ResumeURL != nil && h.media != nil {
		link := h.media.URL(*c.ResumeURL)
		c.ResumeURL = &link
	}
	return c
}

// UploadResume accepts a multipart resume file for a candidate, stores it privately on the
// media store, and records its key on the candidate; the replaced resume is deleted.
func (h *RecruitmentHandler) UploadResume(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	if !h.media.Enabled() {
		writeError(w, http.StatusServiceUnavailable, "media_unavailable", "media storage not configured")
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	cand, err := h.svc.GetCandidate(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "candidate not found")
		return
	}
	if err := r.ParseMultipartForm(10 << 20); err != nil { // 10 MiB cap
		writeError(w, http.StatusBadRequest, "bad_request", "invalid multipart form")
		return
	}
	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "missing 'file' field")
		return
	}
	defer func() { _ = file.Close() }()

	rel, err := h.media.SaveResume(r.Context(), scope.TenantID, id, header.Filename, file)
	if err != nil {
		writeError(w, http.StatusBadRequest, "upload_failed", err.Error())
		return
	}
	row, err := h.svc.SetCandidateResume(r.Context(), scope.TenantID, id, rel)
	if err != nil {
		writeError(w, http.StatusBadRequest, "save_failed", err.Error())
		return
	}
	// The replaced resume is deleted once the candidate points at the new one.
	if cand.ResumeURL != nil {
		if err := h.media.Release(r.Context(), *cand.ResumeURL, rel); err != nil {
			h.log.Warn("replaced resume not deleted", zap.Error(err))
		}
	}
	writeJSON(w, http.StatusOK, map[string]any{"candidate": h.withResumeLink(row), "resume_url": h.media.URL(rel)})
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
	views, err := h.svc.DescribeApplications(r.Context(), scope.TenantID, rows)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list applications")
		return
	}
	writePagedSlice(w, views, pagination.Parse(r))
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
	Status          string `json:"status"`
	CreateEmployee  bool   `json:"create_employee"`
	InterviewDate   string `json:"interview_date"`
	OfferDetails    string `json:"offer_details"`
	RejectionReason string `json:"rejection_reason"`
}

func (b transitionBody) meta() recruitment.TransitionMeta {
	m := recruitment.TransitionMeta{OfferDetails: b.OfferDetails, RejectionReason: b.RejectionReason}
	if b.InterviewDate != "" {
		if t, err := time.Parse("2006-01-02", b.InterviewDate); err == nil {
			m.InterviewDate = &t
		}
	}
	return m
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
	res, err := h.svc.Transition(r.Context(), scope.TenantID, id, b.Status, b.CreateEmployee, b.meta())
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
	writePagedSlice(w, rows, pagination.Parse(r))
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
	writePagedSlice(w, rows, pagination.Parse(r))
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

type updateTaskBody struct {
	AssignedTo string `json:"assigned_to"`
	DueDate    string `json:"due_date"`
}

// UpdateTask sets a task's assignee and/or due date.
func (h *RecruitmentHandler) UpdateTask(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	taskID, err := uuid.Parse(chi.URLParam(r, "taskID"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid task id")
		return
	}
	var b updateTaskBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	var in recruitment.TaskUpdate
	if b.AssignedTo != "" {
		if id, e := uuid.Parse(b.AssignedTo); e == nil {
			in.AssignedTo = &id
		}
	}
	if b.DueDate == "" {
		in.ClearDue = true
	} else if t, e := time.Parse("2006-01-02", b.DueDate); e == nil {
		in.DueDate = &t
	}
	row, err := h.svc.UpdateTask(r.Context(), scope.TenantID, taskID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

type addTaskBody struct {
	Category string `json:"category"`
	Title    string `json:"title"`
}

// AddTask appends a custom task to an onboarding checklist.
func (h *RecruitmentHandler) AddTask(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permRecruitmentManage) {
		return
	}
	onboardingID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b addTaskBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.AddTask(r.Context(), scope.TenantID, onboardingID, b.Category, b.Title)
	if err != nil {
		writeError(w, http.StatusBadRequest, "add_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}
