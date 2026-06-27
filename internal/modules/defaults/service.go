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

// EnsureAll seeds every default reference set for a tenant. Idempotent + best-effort ordered:
// each Ensure* is independent, so a failure in one is returned but does not corrupt the others.
func (s *Service) EnsureAll(ctx context.Context, tenantID uuid.UUID) error {
	if tenantID == uuid.Nil {
		return fmt.Errorf("defaults: empty tenant id")
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
	if err := s.seq.EnsureDefaults(ctx, tenantID); err != nil {
		return fmt.Errorf("defaults: document sequences: %w", err)
	}
	return nil
}
