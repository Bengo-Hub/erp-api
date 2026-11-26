package defaults

import (
	"context"
	"fmt"
	"strconv"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisalquestion"
	"github.com/Bengo-Hub/erp-api/internal/ent/appraisaltemplate"
	"github.com/Bengo-Hub/erp-api/internal/ent/appsetting"
	"github.com/Bengo-Hub/erp-api/internal/ent/leavecategory"
	"github.com/Bengo-Hub/erp-api/internal/ent/predicate"
)

// PlatformRevisionKey records which corrections of the platform's seeded rows have run, so each
// runs once and a later change by the platform owner is never undone.
const PlatformRevisionKey = "defaults.platform_revision"

// platformRevision is the latest correction.
const platformRevision = 1

// revisePlatform brings rows the platform seeded before the defaults grew new fields up to the
// current defaults. Revision 1: the default template's questions lacked category, weight and max
// score (only NULL fields are filled, matched by question text), and the default leave types
// lacked the paid flag (a type the defaults mark unpaid is set unpaid, matched by name).
func (s *Service) revisePlatform(ctx context.Context, system uuid.UUID) error {
	done := 0
	row, err := s.orm.AppSetting.Query().Where(appsetting.TenantID(system), appsetting.AppKey(PlatformRevisionKey)).Only(ctx)
	switch {
	case err == nil:
		done, _ = strconv.Atoi(row.Value)
	case !ent.IsNotFound(err):
		return fmt.Errorf("defaults: load platform revision: %w", err)
	}
	if done >= platformRevision {
		return nil
	}

	tpl, err := s.orm.AppraisalTemplate.Query().
		Where(appraisaltemplate.TenantID(system), appraisaltemplate.Name(defaultTemplateName)).First(ctx)
	if err != nil && !ent.IsNotFound(err) {
		return fmt.Errorf("defaults: load platform template: %w", err)
	}
	if tpl != nil {
		for _, q := range defaultAppraisalQuestions {
			base := []predicate.AppraisalQuestion{appraisalquestion.TenantID(system), appraisalquestion.TemplateID(tpl.ID), appraisalquestion.QuestionText(q.text)}
			if q.category != "" {
				if _, err := s.orm.AppraisalQuestion.Update().Where(append(base, appraisalquestion.CategoryIsNil())...).
					SetCategory(q.category).Save(ctx); err != nil {
					return fmt.Errorf("defaults: question category: %w", err)
				}
			}
			if q.weight > 0 {
				if _, err := s.orm.AppraisalQuestion.Update().Where(append(base, appraisalquestion.WeightIsNil())...).
					SetWeight(q.weight).Save(ctx); err != nil {
					return fmt.Errorf("defaults: question weight: %w", err)
				}
			}
			if q.maxScore > 0 {
				if _, err := s.orm.AppraisalQuestion.Update().Where(append(base, appraisalquestion.MaxScoreIsNil())...).
					SetMaxScore(q.maxScore).Save(ctx); err != nil {
					return fmt.Errorf("defaults: question max score: %w", err)
				}
			}
		}
	}
	for _, c := range defaultLeaveCategories {
		if c.isPaid {
			continue
		}
		if _, err := s.orm.LeaveCategory.Update().
			Where(leavecategory.TenantID(system), leavecategory.Name(c.name), leavecategory.IsPaid(true)).
			SetIsPaid(false).Save(ctx); err != nil {
			return fmt.Errorf("defaults: leave paid flag: %w", err)
		}
	}

	err = s.orm.AppSetting.Create().SetTenantID(system).SetAppKey(PlatformRevisionKey).SetValue(strconv.Itoa(platformRevision)).
		OnConflictColumns(appsetting.FieldTenantID, appsetting.FieldAppKey).UpdateNewValues().Exec(ctx)
	if err != nil {
		return fmt.Errorf("defaults: save platform revision: %w", err)
	}
	return nil
}
