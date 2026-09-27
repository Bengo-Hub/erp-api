package payroll

import (
	"context"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/casualpayment"
	"github.com/Bengo-Hub/erp-api/internal/ent/expenseclaim"
)

// LookupOption is a {value,label} pair for the cost-allocation comboboxes.
type LookupOption struct {
	Value string `json:"value"`
	Label string `json:"label"`
}

// fallbackLookupLimit bounds each distinct-id read: the fallback feeds a combobox, and the
// database returns distinct ids (SELECT DISTINCT ... LIMIT), never every claim row.
const fallbackLookupLimit = 500

// mergeOptions de-duplicates ids from several sources into combobox options (id as label; the
// fallback has no names).
func mergeOptions(lists ...[]uuid.UUID) []LookupOption {
	seen := map[uuid.UUID]bool{}
	out := []LookupOption{}
	for _, ids := range lists {
		for _, id := range ids {
			if id == uuid.Nil || seen[id] {
				continue
			}
			seen[id] = true
			out = append(out, LookupOption{Value: id.String(), Label: id.String()})
		}
	}
	return out
}

// DistinctProjectIDs returns the distinct project ids already referenced on tenant claims +
// casual-labour records. This is the FALLBACK source for the project lookup when projects-api
// is unavailable/unconfigured: it never fabricates a project list, only surfaces ids the ERP
// has actually used so the combobox stays useful offline.
func (s *Service) DistinctProjectIDs(ctx context.Context, tenantID uuid.UUID) ([]LookupOption, error) {
	var fromClaims, fromCasuals []uuid.UUID
	if err := s.orm.ExpenseClaim.Query().
		Where(expenseclaim.TenantID(tenantID), expenseclaim.ProjectIDNotNil()).
		Unique(true).Limit(fallbackLookupLimit).
		Select(expenseclaim.FieldProjectID).Scan(ctx, &fromClaims); err != nil {
		return nil, err
	}
	if err := s.orm.CasualPayment.Query().
		Where(casualpayment.TenantID(tenantID), casualpayment.ProjectIDNotNil()).
		Unique(true).Limit(fallbackLookupLimit).
		Select(casualpayment.FieldProjectID).Scan(ctx, &fromCasuals); err != nil {
		return nil, err
	}
	return mergeOptions(fromClaims, fromCasuals), nil
}

// DistinctCostCenterIDs returns the distinct cost-center ids already referenced on tenant
// claims + casual-labour records (fallback source for the cost-center lookup).
func (s *Service) DistinctCostCenterIDs(ctx context.Context, tenantID uuid.UUID) ([]LookupOption, error) {
	var fromClaims, fromCasuals []uuid.UUID
	if err := s.orm.ExpenseClaim.Query().
		Where(expenseclaim.TenantID(tenantID), expenseclaim.CostCenterIDNotNil()).
		Unique(true).Limit(fallbackLookupLimit).
		Select(expenseclaim.FieldCostCenterID).Scan(ctx, &fromClaims); err != nil {
		return nil, err
	}
	if err := s.orm.CasualPayment.Query().
		Where(casualpayment.TenantID(tenantID), casualpayment.CostCenterIDNotNil()).
		Unique(true).Limit(fallbackLookupLimit).
		Select(casualpayment.FieldCostCenterID).Scan(ctx, &fromCasuals); err != nil {
		return nil, err
	}
	return mergeOptions(fromClaims, fromCasuals), nil
}
