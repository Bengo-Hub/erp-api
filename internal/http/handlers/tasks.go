package handlers

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/tasks"
)

// Tasks RBAC permission codes.
const (
	permTaskView   = "tasks.view"
	permTaskManage = "tasks.manage"
)

// TasksHandler serves /api/v1/tasks/*.
type TasksHandler struct {
	log *zap.Logger
	svc *tasks.Service
}

func NewTasksHandler(log *zap.Logger, svc *tasks.Service) *TasksHandler {
	return &TasksHandler{log: log.Named("tasks"), svc: svc}
}

func (h *TasksHandler) RegisterRoutes(r chi.Router) {
	r.Route("/tasks", func(tr chi.Router) {
		tr.Get("/", h.List)
		tr.Post("/", h.Create)
		tr.Get("/{id}", h.Get)
		tr.Put("/{id}", h.Update)
		tr.Delete("/{id}", h.Delete)
		tr.Patch("/{id}/status", h.SetStatus)
		tr.Patch("/{id}/progress", h.SetProgress)
		tr.Post("/{id}/comments", h.AddComment)
	})
}

func (h *TasksHandler) List(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTaskView) {
		return
	}
	rows, err := h.svc.List(r.Context(), scope.TenantID, tasks.ListFilter{
		Status:     r.URL.Query().Get("status"),
		AssigneeID: optionalUUIDParam(r, "assignee_id"),
	})
	if err != nil {
		h.log.Error("list tasks", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list tasks")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

func (h *TasksHandler) Get(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTaskView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.Get(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "task not found")
		return
	}
	writeJSON(w, http.StatusOK, row)
}

type taskBody struct {
	Title       string  `json:"title"`
	Description string  `json:"description"`
	Status      string  `json:"status"`
	Priority    string  `json:"priority"`
	AssigneeID  *string `json:"assignee_employee_id"`
	Category    string  `json:"category"`
	DueDate     string  `json:"due_date"`
}

func (h *TasksHandler) Create(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTaskManage) {
		return
	}
	var body taskBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	uid := scope.UserID
	in := tasks.CreateInput{
		Title: body.Title, Description: body.Description, Status: body.Status,
		Priority: body.Priority, Category: body.Category, CreatedBy: &uid,
		AssigneeID: parseOptUUID(body.AssigneeID), DueDate: parseOptDate(body.DueDate),
	}
	row, err := h.svc.Create(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *TasksHandler) Update(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTaskManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body taskBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	uid := scope.UserID
	in := tasks.UpdateInput{ActingUser: &uid, AssigneeID: parseOptUUID(body.AssigneeID), DueDate: parseOptDate(body.DueDate)}
	if body.Title != "" {
		in.Title = &body.Title
	}
	if body.Description != "" {
		in.Description = &body.Description
	}
	if body.Priority != "" {
		in.Priority = &body.Priority
	}
	if body.Category != "" {
		in.Category = &body.Category
	}
	row, err := h.svc.Update(r.Context(), scope.TenantID, id, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *TasksHandler) SetStatus(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTaskManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body struct {
		Status string `json:"status"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	uid := scope.UserID
	row, err := h.svc.SetStatus(r.Context(), scope.TenantID, id, body.Status, &uid)
	if err != nil {
		writeError(w, http.StatusBadRequest, "status_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *TasksHandler) SetProgress(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTaskManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body struct {
		Progress int `json:"progress"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	uid := scope.UserID
	row, err := h.svc.SetProgress(r.Context(), scope.TenantID, id, body.Progress, &uid)
	if err != nil {
		writeError(w, http.StatusBadRequest, "progress_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *TasksHandler) AddComment(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTaskManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body struct {
		Body string `json:"body"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	uid := scope.UserID
	row, err := h.svc.AddComment(r.Context(), scope.TenantID, id, body.Body, &uid)
	if err != nil {
		writeError(w, http.StatusBadRequest, "comment_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *TasksHandler) Delete(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permTaskManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.Delete(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

// parseOptUUID parses an optional UUID pointer from a string pointer.
func parseOptUUID(s *string) *uuid.UUID {
	if s == nil || *s == "" {
		return nil
	}
	id, err := uuid.Parse(*s)
	if err != nil {
		return nil
	}
	return &id
}

// parseOptDate parses an optional YYYY-MM-DD/RFC3339 date.
func parseOptDate(s string) *time.Time {
	if s == "" {
		return nil
	}
	t, err := parseDate(s)
	if err != nil {
		return nil
	}
	return &t
}
