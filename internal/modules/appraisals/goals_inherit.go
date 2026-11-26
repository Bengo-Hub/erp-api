package appraisals

import (
	"context"
	"errors"
	"fmt"
	"reflect"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/goal"
	"github.com/Bengo-Hub/erp-api/internal/modules/inherited"
)

// The goal library follows the inherit and customise model too: the platform's sample goals are
// template goals of the system tenant every company uses; a company changes one's description,
// category or weight with an override record, and its own template goal of the same title takes
// the platform one's place. Goals given to employees are always the company's own.

// GoalOverridesKey is the AppSetting key holding a company's changes to inherited sample goals.
const GoalOverridesKey = "appraisal.goals"

// ErrInheritedGoal refuses renaming, assigning or deleting a platform sample goal.
var ErrInheritedGoal = errors.New("a platform sample goal keeps its title and cannot be deleted; add your own goal instead")

// GoalOverride is a company's change to an inherited sample goal.
type GoalOverride struct {
	Description *string        `json:"description,omitempty"`
	Metadata    map[string]any `json:"metadata,omitempty"`
}

func (o GoalOverride) apply(g *ent.Goal) *ent.Goal {
	c := *g
	if o.Description != nil {
		c.Description = *o.Description
	}
	if o.Metadata != nil {
		c.Metadata = o.Metadata
	}
	return &c
}

// inheritedGoals is the platform's sample goals a company uses, with its changes.
func (s *Service) inheritedGoals(ctx context.Context, tenantID uuid.UUID) ([]*ent.Goal, error) {
	if s.systemTenant == uuid.Nil || s.systemTenant == tenantID {
		return nil, nil
	}
	rows, err := s.orm.Goal.Query().
		Where(goal.TenantIDIn(tenantID, s.systemTenant), goal.IsTemplate(true)).
		Order(ent.Desc(goal.FieldCreatedAt)).All(ctx)
	if err != nil {
		return nil, err
	}
	own := map[string]bool{}
	for _, g := range rows {
		if g.TenantID == tenantID {
			own[inherited.NameKey(g.Title)] = true
		}
	}
	changes, err := inherited.Load[GoalOverride](ctx, s.orm, tenantID, GoalOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	var out []*ent.Goal
	for _, g := range rows {
		if g.TenantID == tenantID || own[inherited.NameKey(g.Title)] {
			continue
		}
		if o, ok := changes[g.ID.String()]; ok {
			g = o.apply(g)
		}
		out = append(out, g)
	}
	return out, nil
}

func (s *Service) inheritedGoal(ctx context.Context, tenantID, id uuid.UUID) (*ent.Goal, error) {
	rows, err := s.inheritedGoals(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	for _, g := range rows {
		if g.ID == id {
			return g, nil
		}
	}
	return nil, &ent.NotFoundError{}
}

// customiseGoal keeps a company's description, category and weight for an inherited sample goal.
func (s *Service) customiseGoal(ctx context.Context, tenantID uuid.UUID, current *ent.Goal, in GoalInput) (*ent.Goal, error) {
	if inherited.NameKey(in.Title) != inherited.NameKey(current.Title) || in.EmployeeID != nil {
		return nil, ErrInheritedGoal
	}
	platform, err := s.orm.Goal.Get(ctx, current.ID)
	if err != nil {
		return nil, err
	}
	md, err := in.metadata(current.Metadata)
	if err != nil {
		return nil, err
	}
	var o GoalOverride
	if in.Description != platform.Description {
		d := in.Description
		o.Description = &d
	}
	if !reflect.DeepEqual(md, platform.Metadata) && !(len(md) == 0 && len(platform.Metadata) == 0) {
		o.Metadata = md
	}
	m, err := inherited.Load[GoalOverride](ctx, s.orm, tenantID, GoalOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	if o.Description == nil && o.Metadata == nil {
		delete(m, current.ID.String())
	} else {
		m[current.ID.String()] = o
	}
	if err := inherited.Save(ctx, s.orm, tenantID, GoalOverridesKey, m); err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	return o.apply(platform), nil
}

// RevertGoal drops a company's changes to an inherited sample goal.
func (s *Service) RevertGoal(ctx context.Context, tenantID, id uuid.UUID) (*ent.Goal, error) {
	if _, err := s.inheritedGoal(ctx, tenantID, id); err != nil {
		return nil, err
	}
	m, err := inherited.Load[GoalOverride](ctx, s.orm, tenantID, GoalOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	if _, ok := m[id.String()]; !ok {
		return nil, ErrNothingToRevert
	}
	delete(m, id.String())
	if err := inherited.Save(ctx, s.orm, tenantID, GoalOverridesKey, m); err != nil {
		return nil, fmt.Errorf("appraisals: %w", err)
	}
	return s.orm.Goal.Get(ctx, id)
}
