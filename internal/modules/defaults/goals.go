package defaults

import (
	"context"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/goal"
)

// defaultGoalLibrary are common, reusable appraisal/performance goal templates (is_template=true,
// no employee) a tenant inherits and can assign to employees or clone. Tenants may add their own.
var defaultGoalLibrary = []struct{ title, description string }{
	{"Improve Customer Satisfaction", "Raise the customer satisfaction (CSAT) score for the period."},
	{"Complete Professional Certification", "Obtain a relevant professional certification or qualification."},
	{"Increase Sales / Revenue", "Grow revenue or sales volume against the agreed target."},
	{"Reduce Operational Costs", "Identify and deliver measurable cost savings in your area."},
	{"Enhance Team Collaboration", "Improve cross-functional collaboration and knowledge sharing."},
	{"Develop Leadership Skills", "Take on a stretch assignment or mentor a colleague."},
	{"Improve Process Efficiency", "Streamline a recurring process to cut turnaround time."},
	{"Achieve Quality Targets", "Meet or exceed the defined quality / accuracy standard."},
	{"Strengthen Compliance & Safety", "Maintain full compliance with policy, safety and statutory requirements."},
	{"Drive Innovation", "Propose and pilot an improvement or new idea in your function."},
}

// EnsureGoalLibrary idempotently seeds the common goal-template library for a tenant. Skips any
// template whose title already exists (the library tab in the UI reads is_template=true goals).
func (s *Service) EnsureGoalLibrary(ctx context.Context, tenantID uuid.UUID) error {
	for _, g := range defaultGoalLibrary {
		exists, err := s.orm.Goal.Query().
			Where(goal.TenantID(tenantID), goal.IsTemplate(true), goal.Title(g.title)).Exist(ctx)
		if err != nil {
			return err
		}
		if exists {
			continue
		}
		if _, err := s.orm.Goal.Create().
			SetTenantID(tenantID).
			SetTitle(g.title).
			SetDescription(g.description).
			SetIsTemplate(true).
			SetStatus(goal.StatusNotStarted).
			SetProgress(0).
			Save(ctx); err != nil {
			return err
		}
	}
	return nil
}
