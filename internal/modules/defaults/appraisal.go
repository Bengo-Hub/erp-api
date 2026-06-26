package defaults

import (
	"context"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalquestion"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisaltemplate"
)

// defaultTemplateName is the name of the seeded default appraisal template (used as the
// idempotency key per tenant).
const defaultTemplateName = "Standard Performance Review"

// defaultAppraisalQuestion is one seeded question on the default template.
type defaultAppraisalQuestion struct {
	text         string
	questionType appraisalquestion.QuestionType
	order        int
}

// defaultAppraisalQuestions are standard rating-scale competencies plus two free-text prompts.
var defaultAppraisalQuestions = []defaultAppraisalQuestion{
	{"Quality of Work", appraisalquestion.QuestionTypeRating, 1},
	{"Productivity", appraisalquestion.QuestionTypeRating, 2},
	{"Communication", appraisalquestion.QuestionTypeRating, 3},
	{"Teamwork", appraisalquestion.QuestionTypeRating, 4},
	{"Initiative", appraisalquestion.QuestionTypeRating, 5},
	{"Punctuality", appraisalquestion.QuestionTypeRating, 6},
	{"Key Achievements", appraisalquestion.QuestionTypeText, 7},
	{"Areas for Improvement", appraisalquestion.QuestionTypeText, 8},
}

// EnsureAppraisalTemplate idempotently creates one default appraisal template + its standard
// questions for a tenant. If the template already exists (by name), it is left untouched and
// the questions are not re-created.
func (s *Service) EnsureAppraisalTemplate(ctx context.Context, tenantID uuid.UUID) error {
	exists, err := s.orm.AppraisalTemplate.Query().
		Where(appraisaltemplate.TenantID(tenantID), appraisaltemplate.Name(defaultTemplateName)).Exist(ctx)
	if err != nil {
		return err
	}
	if exists {
		return nil
	}
	tpl, err := s.orm.AppraisalTemplate.Create().
		SetTenantID(tenantID).
		SetName(defaultTemplateName).
		SetDescription("Default competency-based performance review template").
		SetIsActive(true).
		Save(ctx)
	if err != nil {
		return err
	}
	for _, q := range defaultAppraisalQuestions {
		if _, err := s.orm.AppraisalQuestion.Create().
			SetTenantID(tenantID).
			SetTemplateID(tpl.ID).
			SetQuestionText(q.text).
			SetQuestionType(q.questionType).
			SetIsRequired(q.questionType == appraisalquestion.QuestionTypeRating).
			SetOrder(q.order).
			Save(ctx); err != nil {
			return err
		}
	}
	return nil
}
