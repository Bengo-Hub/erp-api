package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/appraisals"
)

// Appraisals RBAC permission codes.
const (
	permAppraisalView   = "hrm.appraisal.view"
	permAppraisalManage = "hrm.appraisal.manage"
)

// AppraisalsHandler serves /api/v1/hrm/appraisals/*.
type AppraisalsHandler struct {
	log *zap.Logger
	svc *appraisals.Service
}

func NewAppraisalsHandler(log *zap.Logger, svc *appraisals.Service) *AppraisalsHandler {
	return &AppraisalsHandler{log: log.Named("hrm.appraisals"), svc: svc}
}

func (h *AppraisalsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/hrm/appraisals", func(ar chi.Router) {
		ar.Get("/cycles", h.ListCycles)
		ar.Post("/cycles", h.CreateCycle)
		ar.Put("/cycles/{id}/status", h.SetCycleStatus)

		ar.Get("/templates", h.ListTemplates)
		ar.Post("/templates", h.CreateTemplate)
		ar.Get("/templates/{id}/questions", h.ListQuestions)
		ar.Post("/templates/{id}/questions", h.AddQuestion)

		ar.Get("/", h.ListAppraisals)
		ar.Post("/", h.CreateAppraisal)
		ar.Put("/{id}/status", h.SetAppraisalStatus)
		ar.Get("/{id}/responses", h.ListResponses)
		ar.Post("/{id}/responses", h.AddResponse)

		ar.Get("/goals", h.ListGoals)
		ar.Post("/goals", h.CreateGoal)
		ar.Post("/goals/{id}/progress", h.AddProgress)
		ar.Get("/goals/{id}/progress", h.ListProgress)
	})
}

// ---- Cycles ----

func (h *AppraisalsHandler) ListCycles(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalView) {
		return
	}
	rows, err := h.svc.ListCycles(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list cycles")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type cycleBody struct {
	Name        string `json:"name"`
	Description string `json:"description"`
	StartDate   string `json:"start_date"`
	EndDate     string `json:"end_date"`
	DueDate     string `json:"due_date"`
}

func (h *AppraisalsHandler) CreateCycle(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	var b cycleBody
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
	in := appraisals.CycleInput{Name: b.Name, Description: b.Description, StartDate: start, EndDate: end}
	if d, derr := parseDate(b.DueDate); derr == nil {
		in.DueDate = &d
	}
	uid := scope.UserID
	in.CreatedBy = &uid
	row, err := h.svc.CreateCycle(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *AppraisalsHandler) SetCycleStatus(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
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
	row, err := h.svc.SetCycleStatus(r.Context(), scope.TenantID, id, b.Status)
	if err != nil {
		writeError(w, http.StatusBadRequest, "transition_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// ---- Templates + questions ----

func (h *AppraisalsHandler) ListTemplates(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalView) {
		return
	}
	rows, err := h.svc.ListTemplates(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list templates")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type templateBody struct {
	Name        string `json:"name"`
	Description string `json:"description"`
}

func (h *AppraisalsHandler) CreateTemplate(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	var b templateBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	uid := scope.UserID
	row, err := h.svc.CreateTemplate(r.Context(), scope.TenantID, b.Name, b.Description, &uid)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *AppraisalsHandler) ListQuestions(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	rows, err := h.svc.ListQuestions(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list questions")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type questionBody struct {
	QuestionText string `json:"question_text"`
	QuestionType string `json:"question_type"`
	IsRequired   *bool  `json:"is_required"`
	Order        int    `json:"order"`
}

func (h *AppraisalsHandler) AddQuestion(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	templateID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b questionBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.AddQuestion(r.Context(), scope.TenantID, appraisals.QuestionInput{
		TemplateID: templateID, QuestionText: b.QuestionText, QuestionType: b.QuestionType,
		IsRequired: b.IsRequired == nil || *b.IsRequired, Order: b.Order,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

// ---- Appraisals ----

func (h *AppraisalsHandler) ListAppraisals(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalView) {
		return
	}
	cycleID := optionalUUIDParam(r, "cycle_id")
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListAppraisals(r.Context(), scope.TenantID, cycleID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list appraisals")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type appraisalBody struct {
	CycleID     string `json:"cycle_id"`
	EmployeeID  string `json:"employee_id"`
	EvaluatorID string `json:"evaluator_id"`
	TemplateID  string `json:"template_id"`
}

func (h *AppraisalsHandler) CreateAppraisal(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	var b appraisalBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	cycleID, err := uuid.Parse(b.CycleID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid cycle_id")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	in := appraisals.AppraisalInput{CycleID: cycleID, EmployeeID: empID}
	if b.EvaluatorID != "" {
		if eid, perr := uuid.Parse(b.EvaluatorID); perr == nil {
			in.EvaluatorID = &eid
		}
	}
	if b.TemplateID != "" {
		if tid, perr := uuid.Parse(b.TemplateID); perr == nil {
			in.TemplateID = &tid
		}
	}
	row, err := h.svc.CreateAppraisal(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

type appraisalStatusBody struct {
	Status          string `json:"status"`
	OverallRating   string `json:"overall_rating"`
	RejectionReason string `json:"rejection_reason"`
}

func (h *AppraisalsHandler) SetAppraisalStatus(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b appraisalStatusBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.SetAppraisalStatus(r.Context(), scope.TenantID, id, b.Status, b.OverallRating, b.RejectionReason)
	if err != nil {
		writeError(w, http.StatusBadRequest, "transition_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *AppraisalsHandler) ListResponses(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	rows, err := h.svc.ListResponses(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list responses")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type responseBody struct {
	QuestionID string `json:"question_id"`
	Response   string `json:"response"`
	Rating     string `json:"rating"`
}

func (h *AppraisalsHandler) AddResponse(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	appraisalID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b responseBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	questionID, err := uuid.Parse(b.QuestionID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid question_id")
		return
	}
	row, err := h.svc.AddResponse(r.Context(), scope.TenantID, appraisals.ResponseInput{
		AppraisalID: appraisalID, QuestionID: questionID, Response: b.Response, Rating: b.Rating,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

// ---- Goals ----

func (h *AppraisalsHandler) ListGoals(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalView) {
		return
	}
	empID := optionalUUIDParam(r, "employee_id")
	rows, err := h.svc.ListGoals(r.Context(), scope.TenantID, empID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list goals")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type goalBody struct {
	EmployeeID  string `json:"employee_id"`
	Title       string `json:"title"`
	Description string `json:"description"`
	StartDate   string `json:"start_date"`
	EndDate     string `json:"end_date"`
	IsTemplate  bool   `json:"is_template"`
}

func (h *AppraisalsHandler) CreateGoal(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	var b goalBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	empID, err := uuid.Parse(b.EmployeeID)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
		return
	}
	uid := scope.UserID
	in := appraisals.GoalInput{
		EmployeeID: empID, Title: b.Title, Description: b.Description,
		IsTemplate: b.IsTemplate, CreatedBy: &uid,
	}
	if d, derr := parseDate(b.StartDate); derr == nil {
		in.StartDate = &d
	}
	if d, derr := parseDate(b.EndDate); derr == nil {
		in.EndDate = &d
	}
	row, err := h.svc.CreateGoal(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

type progressBody struct {
	Progress int    `json:"progress"`
	Comments string `json:"comments"`
}

func (h *AppraisalsHandler) AddProgress(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	goalID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var b progressBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	uid := scope.UserID
	row, err := h.svc.AddProgress(r.Context(), scope.TenantID, goalID, b.Progress, b.Comments, &uid)
	if err != nil {
		writeError(w, http.StatusBadRequest, "progress_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *AppraisalsHandler) ListProgress(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalView) {
		return
	}
	goalID, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	rows, err := h.svc.ListProgress(r.Context(), scope.TenantID, goalID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list progress")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}
