package appraisals

import (
	"context"
	"errors"
	"fmt"
	"strings"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalquestion"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalresponse"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisaltemplate"
	"github.com/Bengo-Hub/erp-api/internal/modules/inherited"
)

// Appraisal templates and their questions follow the inherit and customise model (package
// inherited): the platform's templates are rows of the system tenant every company uses; a company
// changes a template's description or active flag, or a question's wording and scoring, with an
// override record, and its own template of the same name takes the platform one's place.

// Keys of a company's changes to inherited templates and questions.
const (
	TemplateOverridesKey = "appraisal.templates"
	QuestionOverridesKey = "appraisal.questions"
)

var (
	// ErrInheritedTemplate refuses renaming or deleting a platform template or question.
	ErrInheritedTemplate = errors.New("a platform template keeps its name and questions; change them for your company or add your own template")
	// ErrNothingToRevert is returned when reverting a template or question without changes.
	ErrNothingToRevert = errors.New("there are no changes to revert")
)

// TemplateOverride is a company's change to an inherited template.
type TemplateOverride struct {
	Description *string `json:"description,omitempty"`
	IsActive    *bool   `json:"is_active,omitempty"`
}

// QuestionOverride is a company's change to an inherited question.
type QuestionOverride struct {
	QuestionText *string  `json:"question_text,omitempty"`
	IsRequired   *bool    `json:"is_required,omitempty"`
	Order        *int     `json:"order,omitempty"`
	Category     *string  `json:"category,omitempty"`
	Weight       *float64 `json:"weight,omitempty"`
	MaxScore     *int     `json:"max_score,omitempty"`
}

func (o TemplateOverride) apply(t *ent.AppraisalTemplate) *ent.AppraisalTemplate {
	c := *t
	if o.Description != nil {
		c.Description = *o.Description
	}
	if o.IsActive != nil {
		c.IsActive = *o.IsActive
	}
	return &c
}

func (o QuestionOverride) apply(q *ent.AppraisalQuestion) *ent.AppraisalQuestion {
	c := *q
	if o.QuestionText != nil {
		c.QuestionText = *o.QuestionText
	}
	if o.IsRequired != nil {
		c.IsRequired = *o.IsRequired
	}
	if o.Order != nil {
		c.Order = *o.Order
	}
	if o.Category != nil {
		c.Category = *o.Category
	}
	if o.Weight != nil {
		c.Weight = *o.Weight
	}
	if o.MaxScore != nil {
		c.MaxScore = *o.MaxScore
	}
	return &c
}

// resolvedTemplates is every template a company uses: its own, and the platform's (with its
// changes) that no own template of the same name replaces. Newest first.
func (s *Service) resolvedTemplates(ctx context.Context, tenantID uuid.UUID) ([]*ent.AppraisalTemplate, error) {
	all, err := s.orm.AppraisalTemplate.Query().
		Where(appraisaltemplate.TenantIDIn(s.tenantScope(tenantID)...)).
		Order(ent.Desc(appraisaltemplate.FieldCreatedAt)).All(ctx)
	if err != nil {
		return nil, err
	}
	own := map[string]bool{}
	for _, t := range all {
		if t.TenantID == tenantID {
			own[inherited.NameKey(t.Name)] = true
		}
	}
	changes, err := inherited.Load[TemplateOverride](ctx, s.orm, tenantID, TemplateOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	out := make([]*ent.AppraisalTemplate, 0, len(all))
	for _, t := range all {
		if t.TenantID != tenantID {
			if own[inherited.NameKey(t.Name)] {
				continue
			}
			if o, ok := changes[t.ID.String()]; ok {
				t = o.apply(t)
			}
		}
		out = append(out, t)
	}
	return out, nil
}

// withQuestionChanges applies a company's changes to the inherited questions among rows.
func (s *Service) withQuestionChanges(ctx context.Context, tenantID uuid.UUID, rows []*ent.AppraisalQuestion) ([]*ent.AppraisalQuestion, error) {
	changes, err := inherited.Load[QuestionOverride](ctx, s.orm, tenantID, QuestionOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	if len(changes) == 0 {
		return rows, nil
	}
	out := make([]*ent.AppraisalQuestion, len(rows))
	for i, q := range rows {
		if o, ok := changes[q.ID.String()]; ok && q.TenantID != tenantID {
			q = o.apply(q)
		}
		out[i] = q
	}
	return out, nil
}

// inheritedTemplate is a platform template the company uses.
func (s *Service) inheritedTemplate(ctx context.Context, tenantID, id uuid.UUID) (*ent.AppraisalTemplate, error) {
	tpls, err := s.resolvedTemplates(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	for _, t := range tpls {
		if t.ID == id && t.TenantID != tenantID {
			return t, nil
		}
	}
	return nil, &ent.NotFoundError{}
}

// customiseTemplate keeps a company's description and active flag for an inherited template.
func (s *Service) customiseTemplate(ctx context.Context, tenantID uuid.UUID, current *ent.AppraisalTemplate, name, description string, isActive *bool) (*ent.AppraisalTemplate, error) {
	if inherited.NameKey(name) != inherited.NameKey(current.Name) {
		return nil, ErrInheritedTemplate
	}
	platform, err := s.orm.AppraisalTemplate.Get(ctx, current.ID)
	if err != nil {
		return nil, err
	}
	var o TemplateOverride
	if description != platform.Description {
		o.Description = &description
	}
	if isActive != nil && *isActive != platform.IsActive {
		o.IsActive = isActive
	} else if isActive == nil && current.IsActive != platform.IsActive {
		keep := current.IsActive
		o.IsActive = &keep
	}
	m, err := inherited.Load[TemplateOverride](ctx, s.orm, tenantID, TemplateOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	if o.Description == nil && o.IsActive == nil {
		delete(m, current.ID.String())
	} else {
		m[current.ID.String()] = o
	}
	if err := inherited.Save(ctx, s.orm, tenantID, TemplateOverridesKey, m); err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	return o.apply(platform), nil
}

// RevertTemplate drops a company's changes to an inherited template.
func (s *Service) RevertTemplate(ctx context.Context, tenantID, id uuid.UUID) (*ent.AppraisalTemplate, error) {
	if _, err := s.inheritedTemplate(ctx, tenantID, id); err != nil {
		return nil, err
	}
	m, err := inherited.Load[TemplateOverride](ctx, s.orm, tenantID, TemplateOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	if _, ok := m[id.String()]; !ok {
		return nil, ErrNothingToRevert
	}
	delete(m, id.String())
	if err := inherited.Save(ctx, s.orm, tenantID, TemplateOverridesKey, m); err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	return s.orm.AppraisalTemplate.Get(ctx, id)
}

// inheritedQuestion is a question of a platform template the company uses.
func (s *Service) inheritedQuestion(ctx context.Context, tenantID, id uuid.UUID) (*ent.AppraisalQuestion, error) {
	if s.systemTenant == uuid.Nil || s.systemTenant == tenantID {
		return nil, &ent.NotFoundError{}
	}
	q, err := s.orm.AppraisalQuestion.Query().
		Where(appraisalquestion.TenantID(s.systemTenant), appraisalquestion.ID(id)).Only(ctx)
	if err != nil {
		return nil, err
	}
	if _, err := s.inheritedTemplate(ctx, tenantID, q.TemplateID); err != nil {
		return nil, err
	}
	return q, nil
}

// customiseQuestion keeps a company's wording and scoring for an inherited question that its
// staff have not answered yet.
func (s *Service) customiseQuestion(ctx context.Context, tenantID uuid.UUID, platform *ent.AppraisalQuestion, in QuestionInput) (*ent.AppraisalQuestion, error) {
	if in.TemplateID != uuid.Nil && in.TemplateID != platform.TemplateID {
		return nil, ErrInheritedTemplate
	}
	if in.QuestionType != "" && in.QuestionType != string(platform.QuestionType) {
		return nil, ErrInheritedTemplate
	}
	answered, err := s.orm.AppraisalResponse.Query().
		Where(appraisalresponse.TenantID(tenantID), appraisalresponse.QuestionID(platform.ID)).Exist(ctx)
	if err != nil {
		return nil, fmt.Errorf("appraisals: check answers: %w", err)
	}
	if answered {
		return nil, ErrQuestionAnswered
	}
	var o QuestionOverride
	if text := strings.TrimSpace(in.QuestionText); text != platform.QuestionText {
		o.QuestionText = &text
	}
	if in.IsRequired != platform.IsRequired {
		o.IsRequired = &in.IsRequired
	}
	if in.Order != platform.Order {
		o.Order = &in.Order
	}
	if in.Category != platform.Category {
		o.Category = &in.Category
	}
	if in.Weight != nil && *in.Weight != platform.Weight {
		o.Weight = in.Weight
	}
	if in.MaxScore != nil && *in.MaxScore != platform.MaxScore {
		o.MaxScore = in.MaxScore
	}
	m, err := inherited.Load[QuestionOverride](ctx, s.orm, tenantID, QuestionOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	if o == (QuestionOverride{}) {
		delete(m, platform.ID.String())
	} else {
		m[platform.ID.String()] = o
	}
	if err := inherited.Save(ctx, s.orm, tenantID, QuestionOverridesKey, m); err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	return o.apply(platform), nil
}

// RevertQuestion drops a company's changes to an inherited question.
func (s *Service) RevertQuestion(ctx context.Context, tenantID, id uuid.UUID) (*ent.AppraisalQuestion, error) {
	q, err := s.inheritedQuestion(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	m, err := inherited.Load[QuestionOverride](ctx, s.orm, tenantID, QuestionOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	if _, ok := m[id.String()]; !ok {
		return nil, ErrNothingToRevert
	}
	delete(m, id.String())
	if err := inherited.Save(ctx, s.orm, tenantID, QuestionOverridesKey, m); err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	return q, nil
}
