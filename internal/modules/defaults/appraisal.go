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
	category     string
	weight       float64
	maxScore     int
}

// defaultAppraisalQuestions are standard rating-scale competencies plus two free-text prompts.
// Rating questions carry a weight + a 1-5 max score; the free-text prompts are unweighted.
var defaultAppraisalQuestions = []defaultAppraisalQuestion{
	{"Quality of Work", appraisalquestion.QuestionTypeRating, 1, "Competency", 20, 5},
	{"Productivity", appraisalquestion.QuestionTypeRating, 2, "Competency", 20, 5},
	{"Communication", appraisalquestion.QuestionTypeRating, 3, "Competency", 15, 5},
	{"Teamwork", appraisalquestion.QuestionTypeRating, 4, "Competency", 15, 5},
	{"Initiative", appraisalquestion.QuestionTypeRating, 5, "Competency", 15, 5},
	{"Punctuality", appraisalquestion.QuestionTypeRating, 6, "Competency", 15, 5},
	{"Key Achievements", appraisalquestion.QuestionTypeText, 7, "Open Feedback", 0, 0},
	{"Areas for Improvement", appraisalquestion.QuestionTypeText, 8, "Open Feedback", 0, 0},
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
		c := s.orm.AppraisalQuestion.Create().
			SetTenantID(tenantID).
			SetTemplateID(tpl.ID).
			SetQuestionText(q.text).
			SetQuestionType(q.questionType).
			SetIsRequired(q.questionType == appraisalquestion.QuestionTypeRating).
			SetOrder(q.order).
			SetCategory(q.category)
		if q.weight > 0 {
			c.SetWeight(q.weight)
		}
		if q.maxScore > 0 {
			c.SetMaxScore(q.maxScore)
		}
		if _, err := c.Save(ctx); err != nil {
			return err
		}
	}
	return nil
}
