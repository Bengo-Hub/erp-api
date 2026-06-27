package payroll

import (
	"context"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/casuallaborrecord"
	"github.com/Bengo-Hub/erp-api/internal/ent/expenseclaim"
)

// LookupOption is a {value,label} pair for the cost-allocation comboboxes.
type LookupOption struct {
	Value string `json:"value"`
	Label string `json:"label"`
}

// DistinctProjectIDs returns the distinct project ids already referenced on tenant claims +
// casual-labour records. This is the FALLBACK source for the project lookup when projects-api
// is unavailable/unconfigured — it never fabricates a project list, only surfaces ids the ERP
// has actually used so the combobox stays useful offline.
func (s *Service) DistinctProjectIDs(ctx context.Context, tenantID uuid.UUID) ([]LookupOption, error) {
	seen := map[string]bool{}
	out := []LookupOption{}
	add := func(id *uuid.UUID) {
		if id == nil {
			return
		}
		v := id.String()
		if !seen[v] {
			seen[v] = true
			out = append(out, LookupOption{Value: v, Label: v})
		}
	}
	claims, err := s.orm.ExpenseClaim.Query().
		Where(expenseclaim.TenantID(tenantID), expenseclaim.ProjectIDNotNil()).
		Select(expenseclaim.FieldProjectID).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, c := range claims {
		add(c.ProjectID)
	}
	casuals, err := s.orm.CasualLaborRecord.Query().
		Where(casuallaborrecord.TenantID(tenantID), casuallaborrecord.ProjectIDNotNil()).
		Select(casuallaborrecord.FieldProjectID).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, c := range casuals {
		add(c.ProjectID)
	}
	return out, nil
}

// DistinctCostCenterIDs returns the distinct cost-center ids already referenced on tenant
// claims + casual-labour records (fallback source for the cost-center lookup).
func (s *Service) DistinctCostCenterIDs(ctx context.Context, tenantID uuid.UUID) ([]LookupOption, error) {
	seen := map[string]bool{}
	out := []LookupOption{}
	add := func(id *uuid.UUID) {
		if id == nil {
			return
		}
		v := id.String()
		if !seen[v] {
			seen[v] = true
			out = append(out, LookupOption{Value: v, Label: v})
		}
	}
	claims, err := s.orm.ExpenseClaim.Query().
		Where(expenseclaim.TenantID(tenantID), expenseclaim.CostCenterIDNotNil()).
		Select(expenseclaim.FieldCostCenterID).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, c := range claims {
		add(c.CostCenterID)
	}
	casuals, err := s.orm.CasualLaborRecord.Query().
		Where(casuallaborrecord.TenantID(tenantID), casuallaborrecord.CostCenterIDNotNil()).
		Select(casuallaborrecord.FieldCostCenterID).All(ctx)
	if err != nil {
		return nil, err
	}
	for _, c := range casuals {
		add(c.CostCenterID)
	}
	return out, nil
}
