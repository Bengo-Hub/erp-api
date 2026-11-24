package handlers

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
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
		ar.Put("/cycles/{id}", h.UpdateCycle)
		ar.Patch("/cycles/{id}", h.UpdateCycle)
		ar.Delete("/cycles/{id}", h.DeleteCycle)
		ar.Put("/cycles/{id}/status", h.SetCycleStatus)

		ar.Get("/templates", h.ListTemplates)
		ar.Post("/templates", h.CreateTemplate)
		ar.Get("/templates/{id}/questions", h.ListQuestions)
		ar.Get("/questions", h.ListAllQuestions)
		ar.Post("/templates/{id}/questions", h.AddQuestion)

		ar.Get("/", h.ListAppraisals)
		ar.Post("/", h.CreateAppraisal)
		ar.Get("/{id}", h.GetAppraisal)
		ar.Put("/{id}/status", h.SetAppraisalStatus)
		ar.Get("/{id}/responses", h.ListResponses)
		ar.Post("/{id}/responses", h.AddResponse)

		ar.Get("/goals", h.ListGoals)
		ar.Post("/goals", h.CreateGoal)
		ar.Put("/goals/{id}", h.UpdateGoal)
		ar.Patch("/goals/{id}", h.UpdateGoal)
		ar.Delete("/goals/{id}", h.DeleteGoal)
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

// decodeCycle reads a cycle create/update body; it writes the error response itself.
func decodeCycle(w http.ResponseWriter, r *http.Request) (appraisals.CycleInput, bool) {
	var b cycleBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return appraisals.CycleInput{}, false
	}
	start, err := parseDate(b.StartDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid start_date")
		return appraisals.CycleInput{}, false
	}
	end, err := parseDate(b.EndDate)
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid end_date")
		return appraisals.CycleInput{}, false
	}
	in := appraisals.CycleInput{Name: b.Name, Description: b.Description, StartDate: start, EndDate: end}
	if d, derr := parseDate(b.DueDate); derr == nil {
		in.DueDate = &d
	}
	return in, true
}

// UpdateCycle changes a cycle's name, description and dates (PUT/PATCH /cycles/{id}).
func (h *AppraisalsHandler) UpdateCycle(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := decodeCycle(w, r)
	if !ok {
		return
	}
	row, err := h.svc.UpdateCycle(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "cycle not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// DeleteCycle removes a cycle that holds no appraisals (409 in_use otherwise).
func (h *AppraisalsHandler) DeleteCycle(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	err = h.svc.DeleteCycle(r.Context(), scope.TenantID, id)
	switch {
	case ent.IsNotFound(err):
		writeError(w, http.StatusNotFound, "not_found", "cycle not found")
	case errors.Is(err, appraisals.ErrCycleInUse):
		writeError(w, http.StatusConflict, "in_use", err.Error())
	case err != nil:
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to delete cycle")
	default:
		w.WriteHeader(http.StatusNoContent)
	}
}

func (h *AppraisalsHandler) CreateCycle(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	in, ok := decodeCycle(w, r)
	if !ok {
		return
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
	rows, err := h.svc.ListTemplateViews(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list templates")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

// ListAllQuestions returns the questions of every template the tenant can use, each with
// its template name (the questions screen with no template filter).
func (h *AppraisalsHandler) ListAllQuestions(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalView) {
		return
	}
	rows, err := h.svc.ListAllQuestions(r.Context(), scope.TenantID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list questions")
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
	QuestionText string   `json:"question_text"`
	QuestionType string   `json:"question_type"`
	IsRequired   *bool    `json:"is_required"`
	Order        int      `json:"order"`
	Category     string   `json:"category"`
	Weight       *float64 `json:"weight"`
	MaxScore     *int     `json:"max_score"`
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
		Category: b.Category, Weight: b.Weight, MaxScore: b.MaxScore,
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
	rows, err := h.svc.ListAppraisals(r.Context(), scope.TenantID, cycleID, empID, r.URL.Query().Get("search"))
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list appraisals")
		return
	}
	views, err := h.svc.DescribeAppraisals(r.Context(), scope.TenantID, rows)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list appraisals")
		return
	}
	writePagedSlice(w, views, pagination.Parse(r))
}

// GetAppraisal returns one appraisal with its employee, evaluator, cycle and template names.
func (h *AppraisalsHandler) GetAppraisal(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.GetAppraisal(r.Context(), scope.TenantID, id)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "appraisal not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to load appraisal")
		return
	}
	writeJSON(w, http.StatusOK, row)
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
	// is_template filters the goal library; is_library is the name older screens send.
	rows, err := h.svc.ListGoals(r.Context(), scope.TenantID, appraisals.GoalFilter{
		EmployeeID: optionalUUIDParam(r, "employee_id"),
		IsTemplate: optionalBoolParam(r, "is_template", "is_library"),
	})
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list goals")
		return
	}
	views, err := h.svc.DescribeGoals(r.Context(), scope.TenantID, rows)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list goals")
		return
	}
	writePagedSlice(w, views, pagination.Parse(r))
}

type goalBody struct {
	EmployeeID  string      `json:"employee_id"`
	Title       string      `json:"title"`
	Description string      `json:"description"`
	StartDate   string      `json:"start_date"`
	EndDate     string      `json:"end_date"`
	IsTemplate  bool        `json:"is_template"`
	Category    string      `json:"category"`
	Weight      json.Number `json:"weight"`
}

// decodeGoal reads a goal create/update body; it writes the error response itself. An
// employee id is required unless the body is a library template; on update the service
// checks the stored goal instead (requireEmployee false).
func decodeGoal(w http.ResponseWriter, r *http.Request, requireEmployee bool) (appraisals.GoalInput, bool) {
	var b goalBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return appraisals.GoalInput{}, false
	}
	// Library templates (is_template=true) have no employee; employee goals require one.
	var empID *uuid.UUID
	if b.EmployeeID != "" {
		parsed, err := uuid.Parse(b.EmployeeID)
		if err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "invalid employee_id")
			return appraisals.GoalInput{}, false
		}
		empID = &parsed
	} else if requireEmployee && !b.IsTemplate {
		writeError(w, http.StatusBadRequest, "bad_request", "employee_id is required for a non-template goal")
		return appraisals.GoalInput{}, false
	}
	in := appraisals.GoalInput{
		EmployeeID: empID, Title: b.Title, Description: b.Description,
		IsTemplate: b.IsTemplate, Category: b.Category, Weight: b.Weight.String(),
	}
	if d, derr := parseDate(b.StartDate); derr == nil {
		in.StartDate = &d
	}
	if d, derr := parseDate(b.EndDate); derr == nil {
		in.EndDate = &d
	}
	return in, true
}

// UpdateGoal changes a goal's details (PUT/PATCH /goals/{id}); progress has its own route.
func (h *AppraisalsHandler) UpdateGoal(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	in, ok := decodeGoal(w, r, false)
	if !ok {
		return
	}
	row, err := h.svc.UpdateGoal(r.Context(), scope.TenantID, id, in)
	if ent.IsNotFound(err) {
		writeError(w, http.StatusNotFound, "not_found", "goal not found")
		return
	}
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	views, err := h.svc.DescribeGoals(r.Context(), scope.TenantID, []*ent.Goal{row})
	if err != nil {
		writeJSON(w, http.StatusOK, row)
		return
	}
	writeJSON(w, http.StatusOK, views[0])
}

// DeleteGoal removes a goal and its progress updates.
func (h *AppraisalsHandler) DeleteGoal(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	err = h.svc.DeleteGoal(r.Context(), scope.TenantID, id)
	switch {
	case ent.IsNotFound(err):
		writeError(w, http.StatusNotFound, "not_found", "goal not found")
	case err != nil:
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to delete goal")
	default:
		w.WriteHeader(http.StatusNoContent)
	}
}

func (h *AppraisalsHandler) CreateGoal(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	in, ok := decodeGoal(w, r, true)
	if !ok {
		return
	}
	uid := scope.UserID
	in.CreatedBy = &uid
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
