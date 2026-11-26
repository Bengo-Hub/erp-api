package employees

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent/employeeprojectallocation"
)

// RenameProjectAllocations refreshes the project name copied onto the tenant's allocations of a
// project (projects-api project.updated). Returns how many changed.
func (s *Service) RenameProjectAllocations(ctx context.Context, tenantID, projectID uuid.UUID, name string) (int, error) {
	if name == "" {
		return 0, nil
	}
	n, err := s.orm.EmployeeProjectAllocation.Update().
		Where(employeeprojectallocation.TenantID(tenantID), employeeprojectallocation.ProjectID(projectID),
			employeeprojectallocation.Or(employeeprojectallocation.ProjectNameIsNil(), employeeprojectallocation.ProjectNameNEQ(name))).
		SetProjectName(name).Save(ctx)
	if err != nil {
		return 0, fmt.Errorf("employees: rename project allocations: %w", err)
	}
	return n, nil
}

// EndProjectAllocations ends the tenant's allocations of a closed or deleted project on the day
// it closed (projects-api project.closed / project.deleted). An allocation already ending earlier
// keeps its date. Payroll still splits the closing month to the project and none after it, and
// the history stays. Returns how many changed.
func (s *Service) EndProjectAllocations(ctx context.Context, tenantID, projectID uuid.UUID, closedOn time.Time) (int, error) {
	day := time.Date(closedOn.Year(), closedOn.Month(), closedOn.Day(), 0, 0, 0, 0, time.UTC)
	n, err := s.orm.EmployeeProjectAllocation.Update().
		Where(employeeprojectallocation.TenantID(tenantID), employeeprojectallocation.ProjectID(projectID),
			employeeprojectallocation.Or(employeeprojectallocation.EndDateIsNil(), employeeprojectallocation.EndDateGT(day))).
		SetEndDate(day).Save(ctx)
	if err != nil {
		return 0, fmt.Errorf("employees: end project allocations: %w", err)
	}
	return n, nil
}
