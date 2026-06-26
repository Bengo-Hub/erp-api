package employees

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeprojectallocation"
)

// AllocationInput is the create/update payload for an employee↔project allocation.
type AllocationInput struct {
	EmployeeID        uuid.UUID
	ProjectID         uuid.UUID
	ProjectName       string
	CostCenterID      *uuid.UUID
	AllocationPercent decimal.Decimal
	FixedAmount       *float64
}

// ListAllocations returns project allocations, optionally filtered by employee or project.
func (s *Service) ListAllocations(ctx context.Context, tenantID uuid.UUID, employeeID, projectID *uuid.UUID) ([]*ent.EmployeeProjectAllocation, error) {
	q := s.orm.EmployeeProjectAllocation.Query().Where(employeeprojectallocation.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(employeeprojectallocation.EmployeeID(*employeeID))
	}
	if projectID != nil {
		q = q.Where(employeeprojectallocation.ProjectID(*projectID))
	}
	return q.Order(ent.Desc(employeeprojectallocation.FieldCreatedAt)).All(ctx)
}

// CreateAllocation adds an employee↔project allocation.
func (s *Service) CreateAllocation(ctx context.Context, tenantID uuid.UUID, in AllocationInput) (*ent.EmployeeProjectAllocation, error) {
	if in.EmployeeID == uuid.Nil || in.ProjectID == uuid.Nil {
		return nil, fmt.Errorf("employee_id and project_id are required")
	}
	c := s.orm.EmployeeProjectAllocation.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetProjectID(in.ProjectID).
		SetAllocationPercent(in.AllocationPercent).
		SetNillableCostCenterID(in.CostCenterID)
	if in.ProjectName != "" {
		c = c.SetProjectName(in.ProjectName)
	}
	if in.FixedAmount != nil {
		c = c.SetFixedAmount(*in.FixedAmount)
	}
	return c.Save(ctx)
}

// UpdateAllocation edits an allocation.
func (s *Service) UpdateAllocation(ctx context.Context, tenantID, id uuid.UUID, in AllocationInput) (*ent.EmployeeProjectAllocation, error) {
	u := s.orm.EmployeeProjectAllocation.UpdateOneID(id).Where(employeeprojectallocation.TenantID(tenantID))
	if !in.AllocationPercent.IsZero() {
		u = u.SetAllocationPercent(in.AllocationPercent)
	}
	if in.ProjectName != "" {
		u = u.SetProjectName(in.ProjectName)
	}
	if in.CostCenterID != nil {
		u = u.SetCostCenterID(*in.CostCenterID)
	}
	if in.FixedAmount != nil {
		u = u.SetFixedAmount(*in.FixedAmount)
	}
	return u.Save(ctx)
}

// DeleteAllocation removes an allocation.
func (s *Service) DeleteAllocation(ctx context.Context, tenantID, id uuid.UUID) error {
	_, err := s.orm.EmployeeProjectAllocation.Delete().
		Where(employeeprojectallocation.ID(id), employeeprojectallocation.TenantID(tenantID)).Exec(ctx)
	return err
}
