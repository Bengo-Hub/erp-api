// Package defaults provides idempotent, per-tenant bootstrap of HR/Ops reference data:
// job groups (salary grades), leave categories, a default appraisal template + questions,
// and the default document sequences. These are tenant-scoped business config (NOT shared
// global reference data) — see feedback_shared_core_reference_data — so they are seeded per
// tenant. Every Ensure* method is idempotent (no-op when the rows already exist), making them
// safe to run on every deploy (cmd/seed-defaults) and on first company-settings save.
package defaults

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/business"
)

// Service seeds default tenant reference data. Tenant-scoped, idempotent.
type Service struct {
	orm *ent.Client
	seq *business.SequenceService
}

// NewService builds the defaults seeder. The SequenceService is reused for document sequences.
func NewService(orm *ent.Client) *Service {
	return &Service{orm: orm, seq: business.NewSequenceService(orm)}
}

// EnsureAll seeds what a company needs of its own: the document sequences. Leave types, job
// groups, the appraisal template and sample goals are platform rows every company inherits
// (EnsurePlatform), so nothing of them is copied into a company.
func (s *Service) EnsureAll(ctx context.Context, tenantID uuid.UUID) error {
	if tenantID == uuid.Nil {
		return fmt.Errorf("defaults: empty tenant id")
	}
	if err := s.seq.EnsureDefaults(ctx, tenantID); err != nil {
		return fmt.Errorf("defaults: document sequences: %w", err)
	}
	return nil
}

// EnsurePlatform seeds the shared settings on the platform tenant, once each: a kind the
// platform already holds rows of is left as it is.
func (s *Service) EnsurePlatform(ctx context.Context, tenantID uuid.UUID) error {
	if tenantID == uuid.Nil {
		return fmt.Errorf("defaults: empty platform tenant id")
	}
	if err := s.EnsureJobGroups(ctx, tenantID); err != nil {
		return fmt.Errorf("defaults: job groups: %w", err)
	}
	if err := s.EnsureLeaveCategories(ctx, tenantID); err != nil {
		return fmt.Errorf("defaults: leave categories: %w", err)
	}
	if err := s.EnsureAppraisalTemplate(ctx, tenantID); err != nil {
		return fmt.Errorf("defaults: appraisal template: %w", err)
	}
	if err := s.EnsureGoalLibrary(ctx, tenantID); err != nil {
		return fmt.Errorf("defaults: goal library: %w", err)
	}
	return nil
}
