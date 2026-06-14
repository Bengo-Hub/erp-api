package handlers

import (
	"encoding/json"
	"net/http"

	"github.com/Bengo-Hub/pagination"
	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
)

// Approvals RBAC permission codes.
const (
	permApprovalView   = "approvals.view"
	permApprovalManage = "approvals.manage" // workflow CRUD
	permApprovalDecide = "approvals.decide" // approve/reject/escalate
)

// ApprovalsHandler serves /api/v1/approvals/*.
type ApprovalsHandler struct {
	log *zap.Logger
	svc *approvals.Service
}

func NewApprovalsHandler(log *zap.Logger, svc *approvals.Service) *ApprovalsHandler {
	return &ApprovalsHandler{log: log.Named("approvals"), svc: svc}
}

func (h *ApprovalsHandler) RegisterRoutes(r chi.Router) {
	r.Route("/approvals", func(ar chi.Router) {
		ar.Get("/workflows", h.ListWorkflows)
		ar.Post("/workflows", h.CreateWorkflow)
		ar.Get("/workflows/{id}", h.GetWorkflow)
		ar.Patch("/workflows/{id}/active", h.SetWorkflowActive)
		ar.Delete("/workflows/{id}", h.DeleteWorkflow)

		ar.Get("/requests", h.ListRequests)
		ar.Get("/requests/{id}", h.GetRequest)
		ar.Post("/requests/{id}/approve", h.Approve)
		ar.Post("/requests/{id}/reject", h.Reject)
		ar.Post("/requests/{id}/escalate", h.Escalate)
		ar.Post("/requests/{id}/cancel", h.CancelRequest)
	})
}

// ---- Workflows ----

func (h *ApprovalsHandler) ListWorkflows(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permApprovalView) {
		return
	}
	rows, err := h.svc.ListWorkflows(r.Context(), scope.TenantID, r.URL.Query().Get("module"))
	if err != nil {
		h.log.Error("list workflows", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list workflows")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

type stepBody struct {
	Sequence           int     `json:"sequence"`
	Name               string  `json:"name"`
	ApproverType       string  `json:"approver_type"`
	ApproverRole       string  `json:"approver_role"`
	ApproverEmployeeID *string `json:"approver_employee_id"`
	IsOptional         bool    `json:"is_optional"`
}

type workflowBody struct {
	Module      string     `json:"module"`
	Name        string     `json:"name"`
	Description string     `json:"description"`
	IsActive    *bool      `json:"is_active"`
	Steps       []stepBody `json:"steps"`
}

func (h *ApprovalsHandler) CreateWorkflow(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permApprovalManage) {
		return
	}
	var body workflowBody
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	active := true
	if body.IsActive != nil {
		active = *body.IsActive
	}
	in := approvals.WorkflowInput{
		Module: body.Module, Name: body.Name, Description: body.Description, IsActive: active,
	}
	for _, st := range body.Steps {
		s := approvals.StepInput{
			Sequence: st.Sequence, Name: st.Name, ApproverType: st.ApproverType,
			ApproverRole: st.ApproverRole, IsOptional: st.IsOptional,
		}
		if st.ApproverEmployeeID != nil {
			if id, err := uuid.Parse(*st.ApproverEmployeeID); err == nil {
				s.ApproverEmployeeID = &id
			}
		}
		in.Steps = append(in.Steps, s)
	}
	row, err := h.svc.CreateWorkflow(r.Context(), scope.TenantID, in)
	if err != nil {
		writeError(w, http.StatusBadRequest, "create_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusCreated, row)
}

func (h *ApprovalsHandler) GetWorkflow(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permApprovalView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.GetWorkflow(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "workflow not found")
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *ApprovalsHandler) SetWorkflowActive(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permApprovalManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body struct {
		IsActive bool `json:"is_active"`
	}
	_ = json.NewDecoder(r.Body).Decode(&body)
	row, err := h.svc.SetWorkflowActive(r.Context(), scope.TenantID, id, body.IsActive)
	if err != nil {
		writeError(w, http.StatusBadRequest, "update_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}

func (h *ApprovalsHandler) DeleteWorkflow(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permApprovalManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	if err := h.svc.DeleteWorkflow(r.Context(), scope.TenantID, id); err != nil {
		writeError(w, http.StatusBadRequest, "delete_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"ok": true})
}

// ---- Requests ----

func (h *ApprovalsHandler) ListRequests(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permApprovalView) {
		return
	}
	rows, err := h.svc.ListRequests(r.Context(), scope.TenantID, r.URL.Query().Get("module"), r.URL.Query().Get("status"))
	if err != nil {
		h.log.Error("list requests", zap.Error(err))
		writeError(w, http.StatusInternalServerError, "internal_error", "failed to list approval requests")
		return
	}
	writePagedSlice(w, rows, pagination.Parse(r))
}

func (h *ApprovalsHandler) GetRequest(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permApprovalView) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.GetRequest(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusNotFound, "not_found", "approval request not found")
		return
	}
	writeJSON(w, http.StatusOK, row)
}

type decisionBody struct {
	Comment string `json:"comment"`
}

func (h *ApprovalsHandler) decide(w http.ResponseWriter, r *http.Request, approve, escalate bool) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permApprovalDecide) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	var body decisionBody
	_ = json.NewDecoder(r.Body).Decode(&body)
	uid := scope.UserID
	dec, err := h.svc.Decide(r.Context(), scope.TenantID, approvals.DecisionInput{
		RequestID: id, Approve: approve, Escalate: escalate, Comment: body.Comment, ActedBy: &uid,
	})
	if err != nil {
		writeError(w, http.StatusBadRequest, "decision_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"request": dec.Request, "finished": dec.Finished})
}

func (h *ApprovalsHandler) Approve(w http.ResponseWriter, r *http.Request) {
	h.decide(w, r, true, false)
}
func (h *ApprovalsHandler) Reject(w http.ResponseWriter, r *http.Request) {
	h.decide(w, r, false, false)
}
func (h *ApprovalsHandler) Escalate(w http.ResponseWriter, r *http.Request) {
	h.decide(w, r, true, true)
}

func (h *ApprovalsHandler) CancelRequest(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permApprovalManage) {
		return
	}
	id, err := uuid.Parse(chi.URLParam(r, "id"))
	if err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid id")
		return
	}
	row, err := h.svc.Cancel(r.Context(), scope.TenantID, id)
	if err != nil {
		writeError(w, http.StatusBadRequest, "cancel_failed", err.Error())
		return
	}
	writeJSON(w, http.StatusOK, row)
}
