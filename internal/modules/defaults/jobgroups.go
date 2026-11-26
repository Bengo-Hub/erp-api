package defaults

import (
	"context"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/jobgroup"
)

// defaultJobGroup is one seeded salary grade.
type defaultJobGroup struct {
	title, description string
}

// defaultJobGroups is the standard salary-grade ladder (A–G), Grade A highest. A sensible
// Kenyan corporate default that tenants can rename/extend.
var defaultJobGroups = []defaultJobGroup{
	{"Grade A", "Executive / C-suite"},
	{"Grade B", "Senior Management"},
	{"Grade C", "Middle Management"},
	{"Grade D", "Supervisory"},
	{"Grade E", "Senior Officer"},
	{"Grade F", "Officer"},
	{"Grade G", "Support / Entry"},
}

// EnsureJobGroups idempotently creates the default salary-grade job groups for a tenant.
// Skips any grade whose title already exists for the tenant (case-sensitive title match).
func (s *Service) EnsureJobGroups(ctx context.Context, tenantID uuid.UUID) error {
	// Seeded once: a tenant with any job group keeps what it has (a removed default stays removed).
	if any, err := s.orm.JobGroup.Query().Where(jobgroup.TenantID(tenantID)).Exist(ctx); err != nil || any {
		return err
	}
	for _, g := range defaultJobGroups {
		exists, err := s.orm.JobGroup.Query().
			Where(jobgroup.TenantID(tenantID), jobgroup.Title(g.title)).Exist(ctx)
		if err != nil {
			return err
		}
		if exists {
			continue
		}
		if _, err := s.orm.JobGroup.Create().
			SetTenantID(tenantID).SetTitle(g.title).SetDescription(g.description).Save(ctx); err != nil {
			return err
		}
	}
	return nil
}
