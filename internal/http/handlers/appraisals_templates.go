package handlers

import (
	"encoding/json"
	"errors"
	"net/http"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/appraisals"
)

// writeTemplateError maps template and question edit errors onto HTTP answers.
func writeTemplateError(w http.ResponseWriter, err error, what string) {
	switch {
	case ent.IsNotFound(err):
		writeError(w, http.StatusNotFound, "not_found", what+" not found")
	case errors.Is(err, appraisals.ErrTemplateInUse), errors.Is(err, appraisals.ErrQuestionAnswered):
		writeError(w, http.StatusConflict, "in_use", err.Error())
	default:
		writeError(w, http.StatusBadRequest, "save_failed", clientMessage(err))
	}
}

// UpdateTemplate edits one of the tenant's own templates.
func (h *AppraisalsHandler) UpdateTemplate(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	var b templateBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	row, err := h.svc.UpdateTemplate(r.Context(), scope.TenantID, id, b.Name, b.Description, b.IsActive)
	if err != nil {
		writeTemplateError(w, err, "template")
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// DeleteTemplate removes a template no appraisal uses, with its questions.
func (h *AppraisalsHandler) DeleteTemplate(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	if err := h.svc.DeleteTemplate(r.Context(), scope.TenantID, id); err != nil {
		writeTemplateError(w, err, "template")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// UpdateQuestion edits a question nobody has answered yet.
func (h *AppraisalsHandler) UpdateQuestion(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	var b questionBody
	if err := json.NewDecoder(r.Body).Decode(&b); err != nil {
		writeError(w, http.StatusBadRequest, "bad_request", "invalid JSON body")
		return
	}
	templateID := uuid.Nil
	if b.TemplateID != "" {
		var err error
		if templateID, err = uuid.Parse(b.TemplateID); err != nil {
			writeError(w, http.StatusBadRequest, "bad_request", "invalid template_id")
			return
		}
	}
	row, err := h.svc.UpdateQuestion(r.Context(), scope.TenantID, id, appraisals.QuestionInput{
		TemplateID: templateID, QuestionText: b.QuestionText, QuestionType: b.QuestionType,
		IsRequired: b.IsRequired == nil || *b.IsRequired, Order: b.Order,
		Category: b.Category, Weight: b.Weight, MaxScore: b.MaxScore,
	})
	if err != nil {
		writeTemplateError(w, err, "question")
		return
	}
	writeJSON(w, http.StatusOK, row)
}

// DeleteQuestion removes a question nobody has answered yet.
func (h *AppraisalsHandler) DeleteQuestion(w http.ResponseWriter, r *http.Request) {
	scope, ok := scopeFromRequest(w, r)
	if !ok || !requirePermission(w, scope, permAppraisalManage) {
		return
	}
	id, ok := idParam(w, r)
	if !ok {
		return
	}
	if err := h.svc.DeleteQuestion(r.Context(), scope.TenantID, id); err != nil {
		writeTemplateError(w, err, "question")
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
