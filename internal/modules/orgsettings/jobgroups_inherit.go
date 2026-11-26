package orgsettings

import (
	"context"
	"errors"
	"fmt"
	"sort"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobgroup"
	"github.com/Bengo-Hub/erp-api/internal/modules/inherited"
)

// Job groups follow the inherit and customise model (package inherited): the platform's job
// groups are rows of the system tenant every company uses; a company changes one's description
// with an override record, and its own job group of the same title takes the platform one's place.

// JobGroupOverridesKey is the AppSetting key holding a company's changes to inherited job groups.
const JobGroupOverridesKey = "jobgroups.overrides"

var (
	// ErrJobGroupNotFound is returned for a job group the company does not use.
	ErrJobGroupNotFound = errors.New("job group not found")
	// ErrInheritedJobGroup refuses deleting or renaming a platform job group.
	ErrInheritedJobGroup = errors.New("a platform job group keeps its title and cannot be deleted; add your own job group instead")
	// ErrJobGroupNotCustomised is returned when reverting a job group without changes.
	ErrJobGroupNotCustomised = errors.New("this job group has no changes to revert")
)

// JobGroupOverride is a company's change to an inherited job group.
type JobGroupOverride struct {
	Description *string `json:"description,omitempty"`
}

// JobGroupRow is a job group as a company sees it.
type JobGroupRow struct {
	*ent.JobGroup
	Inherited  bool
	Customised bool
}

// WithSystemTenant sets the tenant whose job groups every company inherits.
func (s *Service) WithSystemTenant(id uuid.UUID) *Service { s.systemTenant = id; return s }

// JobGroupRows is every job group a company uses, by title.
func (s *Service) JobGroupRows(ctx context.Context, tenantID uuid.UUID) ([]JobGroupRow, error) {
	all, err := s.orm.JobGroup.Query().Where(jobgroup.TenantIDIn(inherited.Tenants(s.systemTenant, tenantID)...)).All(ctx)
	if err != nil {
		return nil, err
	}
	own := map[string]bool{}
	for _, g := range all {
		if g.TenantID == tenantID {
			own[inherited.NameKey(g.Title)] = true
		}
	}
	changes, err := inherited.Load[JobGroupOverride](ctx, s.orm, tenantID, JobGroupOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("orgsettings: %w", err)
	}
	out := make([]JobGroupRow, 0, len(all))
	for _, g := range all {
		row := JobGroupRow{JobGroup: g}
		if g.TenantID != tenantID {
			if own[inherited.NameKey(g.Title)] {
				continue
			}
			row.Inherited = true
			if o, ok := changes[g.ID.String()]; ok && o.Description != nil {
				c := *g
				c.Description = o.Description
				row.JobGroup, row.Customised = &c, true
			}
		}
		out = append(out, row)
	}
	sort.SliceStable(out, func(i, j int) bool { return out[i].Title < out[j].Title })
	return out, nil
}

// JobGroupRowByID is one job group the company uses.
func (s *Service) JobGroupRowByID(ctx context.Context, tenantID, id uuid.UUID) (*JobGroupRow, error) {
	rows, err := s.JobGroupRows(ctx, tenantID)
	if err != nil {
		return nil, err
	}
	for i := range rows {
		if rows[i].ID == id {
			return &rows[i], nil
		}
	}
	return nil, ErrJobGroupNotFound
}

// UsesJobGroup reports whether a company can put an employee in the job group.
func (s *Service) UsesJobGroup(ctx context.Context, tenantID, id uuid.UUID) (bool, error) {
	_, err := s.JobGroupRowByID(ctx, tenantID, id)
	if errors.Is(err, ErrJobGroupNotFound) {
		return false, nil
	}
	return err == nil, err
}

// customiseJobGroup keeps a company's description for an inherited job group (the title stays).
func (s *Service) customiseJobGroup(ctx context.Context, tenantID uuid.UUID, row *JobGroupRow, in NamedInput) (*JobGroupRow, error) {
	if in.Title != "" && inherited.NameKey(in.Title) != inherited.NameKey(row.Title) {
		return nil, ErrInheritedJobGroup
	}
	m, err := inherited.Load[JobGroupOverride](ctx, s.orm, tenantID, JobGroupOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("orgsettings: %w", err)
	}
	platform, err := s.orm.JobGroup.Get(ctx, row.ID)
	if err != nil {
		return nil, err
	}
	if in.Description == "" || (platform.Description != nil && *platform.Description == in.Description) {
		delete(m, row.ID.String())
	} else {
		d := in.Description
		m[row.ID.String()] = JobGroupOverride{Description: &d}
	}
	if err := inherited.Save(ctx, s.orm, tenantID, JobGroupOverridesKey, m); err != nil {
		return nil, fmt.Errorf("orgsettings: %w", err)
	}
	return s.JobGroupRowByID(ctx, tenantID, row.ID)
}

// RevertJobGroup drops a company's changes to an inherited job group.
func (s *Service) RevertJobGroup(ctx context.Context, tenantID, id uuid.UUID) (*JobGroupRow, error) {
	row, err := s.JobGroupRowByID(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if !row.Inherited {
		return nil, ErrJobGroupNotFound
	}
	m, err := inherited.Load[JobGroupOverride](ctx, s.orm, tenantID, JobGroupOverridesKey)
	if err != nil {
		return nil, fmt.Errorf("orgsettings: %w", err)
	}
	if _, ok := m[id.String()]; !ok {
		return nil, ErrJobGroupNotCustomised
	}
	delete(m, id.String())
	if err := inherited.Save(ctx, s.orm, tenantID, JobGroupOverridesKey, m); err != nil {
		return nil, fmt.Errorf("orgsettings: %w", err)
	}
	return s.JobGroupRowByID(ctx, tenantID, id)
}
