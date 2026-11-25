package appraisals

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisal"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalquestion"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalresponse"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisaltemplate"
)

var (
	// ErrTemplateInUse is returned when a template that appraisals use is deleted.
	ErrTemplateInUse = errors.New("this template is used by appraisals; make it inactive instead")
	// ErrQuestionAnswered is returned when a question that already has answers is changed or deleted.
	ErrQuestionAnswered = errors.New("this question already has answers, so it cannot be changed or deleted")
)

// UpdateTemplate edits one of the tenant's own templates (the inherited standard template is
// read only and answers not found). isActive nil keeps the current state.
func (s *Service) UpdateTemplate(ctx context.Context, tenantID, id uuid.UUID, name, description string, isActive *bool) (*ent.AppraisalTemplate, error) {
	if strings.TrimSpace(name) == "" {
		return nil, fmt.Errorf("appraisals: name is required")
	}
	t, err := s.orm.AppraisalTemplate.Query().
		Where(appraisaltemplate.TenantID(tenantID), appraisaltemplate.ID(id)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := t.Update().SetName(strings.TrimSpace(name)).SetDescription(description)
	if isActive != nil {
		u = u.SetIsActive(*isActive)
	}
	return u.Save(ctx)
}

// DeleteTemplate removes one of the tenant's own templates with its questions, in one
// transaction (ErrTemplateInUse when an appraisal uses it).
func (s *Service) DeleteTemplate(ctx context.Context, tenantID, id uuid.UUID) error {
	t, err := s.orm.AppraisalTemplate.Query().
		Where(appraisaltemplate.TenantID(tenantID), appraisaltemplate.ID(id)).Only(ctx)
	if err != nil {
		return err
	}
	used, err := s.orm.Appraisal.Query().
		Where(appraisal.TenantID(tenantID), appraisal.TemplateID(t.ID)).Exist(ctx)
	if err != nil {
		return fmt.Errorf("appraisals: check template use: %w", err)
	}
	if used {
		return ErrTemplateInUse
	}
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return err
	}
	defer func() { _ = tx.Rollback() }()
	if _, err := tx.AppraisalQuestion.Delete().
		Where(appraisalquestion.TenantID(tenantID), appraisalquestion.TemplateID(t.ID)).Exec(ctx); err != nil {
		return fmt.Errorf("appraisals: delete template questions: %w", err)
	}
	if err := tx.AppraisalTemplate.DeleteOneID(t.ID).Exec(ctx); err != nil {
		return fmt.Errorf("appraisals: delete template: %w", err)
	}
	return tx.Commit()
}

// editableQuestion loads one of the tenant's own questions that nobody has answered yet.
func (s *Service) editableQuestion(ctx context.Context, tenantID, id uuid.UUID) (*ent.AppraisalQuestion, error) {
	q, err := s.orm.AppraisalQuestion.Query().
		Where(appraisalquestion.TenantID(tenantID), appraisalquestion.ID(id)).Only(ctx)
	if err != nil {
		return nil, err
	}
	answered, err := s.orm.AppraisalResponse.Query().
		Where(appraisalresponse.TenantID(tenantID), appraisalresponse.QuestionID(q.ID)).Exist(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: check answers: %w", err)
	}
	if answered {
		return nil, ErrQuestionAnswered
	}
	return q, nil
}

// UpdateQuestion edits an unanswered question. A new TemplateID moves it to another of the
// tenant's templates.
func (s *Service) UpdateQuestion(ctx context.Context, tenantID, id uuid.UUID, in QuestionInput) (*ent.AppraisalQuestion, error) {
	if strings.TrimSpace(in.QuestionText) == "" {
		return nil, fmt.Errorf("appraisals: question_text is required")
	}
	q, err := s.editableQuestion(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	u := q.Update().SetQuestionText(strings.TrimSpace(in.QuestionText)).
		SetIsRequired(in.IsRequired).SetOrder(in.Order)
	if in.TemplateID != uuid.Nil && in.TemplateID != q.TemplateID {
		ok, terr := s.orm.AppraisalTemplate.Query().
			Where(appraisaltemplate.TenantID(tenantID), appraisaltemplate.ID(in.TemplateID)).Exist(ctx)
		if terr != nil {
			return nil, terr
		}
		if !ok {
			return nil, fmt.Errorf("appraisals: template not found")
		}
		u = u.SetTemplateID(in.TemplateID)
	}
	if in.QuestionType != "" {
		u = u.SetQuestionType(appraisalquestion.QuestionType(in.QuestionType))
	}
	if in.Category != "" {
		u = u.SetCategory(in.Category)
	} else {
		u = u.ClearCategory()
	}
	if in.Weight != nil {
		u = u.SetWeight(*in.Weight)
	} else {
		u = u.ClearWeight()
	}
	if in.MaxScore != nil {
		u = u.SetMaxScore(*in.MaxScore)
	} else {
		u = u.ClearMaxScore()
	}
	return u.Save(ctx)
}

// DeleteQuestion removes an unanswered question.
func (s *Service) DeleteQuestion(ctx context.Context, tenantID, id uuid.UUID) error {
	q, err := s.editableQuestion(ctx, tenantID, id)
	if err != nil {
		return err
	}
	return s.orm.AppraisalQuestion.DeleteOne(q).Exec(ctx)
}
