// Package orgsettings implements tenant-isolated HR reference data CRUD:
// departments, job titles and job groups. These back the erp-ui HRM settings
// screens (/hrm/departments, /hrm/employees/job-titles, /hrm/employees/job-groups).
package orgsettings

import (
	"context"
	"fmt"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/department"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobgroup"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobtitle"
)

// Service holds reference-data CRUD. Every query is tenant-filtered.
type Service struct {
	orm *ent.Client
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// ---- Departments ----

// ListDepartments returns tenant-scoped departments (or rows with NULL tenant_id,
// which are seeded platform reference data).
func (s *Service) ListDepartments(ctx context.Context, tenantID uuid.UUID) ([]*ent.Department, error) {
	return s.orm.Department.Query().
		Where(department.Or(department.TenantID(tenantID), department.TenantIDIsNil())).
		Order(ent.Asc(department.FieldTitle)).
		All(ctx)
}

func (s *Service) GetDepartment(ctx context.Context, tenantID, id uuid.UUID) (*ent.Department, error) {
	return s.orm.Department.Query().
		Where(department.ID(id), department.Or(department.TenantID(tenantID), department.TenantIDIsNil())).
		Only(ctx)
}

// NamedInput is the create/update payload for a named reference record.
type NamedInput struct {
	Title       string
	Code        string
	Description string
}

func (s *Service) CreateDepartment(ctx context.Context, tenantID uuid.UUID, in NamedInput) (*ent.Department, error) {
	if in.Title == "" {
		return nil, fmt.Errorf("orgsettings: department title is required")
	}
	b := s.orm.Department.Create().SetTenantID(tenantID).SetTitle(in.Title)
	if in.Code != "" {
		b = b.SetCode(in.Code)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateDepartment(ctx context.Context, tenantID, id uuid.UUID, in NamedInput) (*ent.Department, error) {
	if _, err := s.GetDepartment(ctx, tenantID, id); err != nil {
		return nil, err
	}
	u := s.orm.Department.UpdateOneID(id)
	if in.Title != "" {
		u = u.SetTitle(in.Title)
	}
	if in.Code != "" {
		u = u.SetCode(in.Code)
	}
	return u.Save(ctx)
}

// DeleteDepartment hard-deletes a tenant's department after clearing the foreign keys that
// reference it, all inside one transaction so it is atomic:
//  1. NULL out HRDetails.department_id for employees placed in this dept (they become
//     unassigned rather than blocking the delete).
//  2. Re-parent child departments to the deleted dept's own parent (or NULL when it had none),
//     preserving the hierarchy instead of orphaning the subtree.
//  3. Hard-delete the department row.
//
// Only the tenant's OWN departments (tenant_id = tenantID) can be deleted — seeded platform
// reference rows (NULL tenant_id) are intentionally not deletable by a tenant admin. Idempotent
// on the FK clears; returns a clear "not found" only when the row truly doesn't belong to the
// tenant, and the real DB error otherwise.
func (s *Service) DeleteDepartment(ctx context.Context, tenantID, id uuid.UUID) error {
	// Load the target first (tenant-owned only) so we know its parent for re-parenting and can
	// distinguish not-found from a real failure.
	dept, err := s.orm.Department.Query().
		Where(department.ID(id), department.TenantID(tenantID)).Only(ctx)
	if ent.IsNotFound(err) {
		return fmt.Errorf("orgsettings: department not found")
	}
	if err != nil {
		return fmt.Errorf("orgsettings: load department: %w", err)
	}

	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return fmt.Errorf("orgsettings: begin tx: %w", err)
	}
	rollback := func(cause error) error {
		_ = tx.Rollback()
		return cause
	}

	// 1) Unassign employees in this department.
	if _, err := tx.HRDetails.Update().
		Where(hrdetails.TenantID(tenantID), hrdetails.DepartmentID(id)).
		ClearDepartmentID().
		Save(ctx); err != nil {
		return rollback(fmt.Errorf("orgsettings: clear employee department links: %w", err))
	}

	// 2) Re-parent child departments to this dept's parent (or NULL).
	childUpd := tx.Department.Update().
		Where(department.TenantID(tenantID), department.ParentDepartmentID(id))
	if dept.ParentDepartmentID != nil {
		childUpd = childUpd.SetParentDepartmentID(*dept.ParentDepartmentID)
	} else {
		childUpd = childUpd.ClearParentDepartmentID()
	}
	if _, err := childUpd.Save(ctx); err != nil {
		return rollback(fmt.Errorf("orgsettings: re-parent child departments: %w", err))
	}

	// 3) Hard-delete the department.
	if err := tx.Department.DeleteOneID(id).Exec(ctx); err != nil {
		return rollback(fmt.Errorf("orgsettings: delete department: %w", err))
	}

	if err := tx.Commit(); err != nil {
		return fmt.Errorf("orgsettings: commit delete: %w", err)
	}
	return nil
}

// ---- Job titles ----

func (s *Service) ListJobTitles(ctx context.Context, tenantID uuid.UUID) ([]*ent.JobTitle, error) {
	return s.orm.JobTitle.Query().
		Where(jobtitle.TenantID(tenantID)).
		Order(ent.Asc(jobtitle.FieldTitle)).
		All(ctx)
}

func (s *Service) GetJobTitle(ctx context.Context, tenantID, id uuid.UUID) (*ent.JobTitle, error) {
	return s.orm.JobTitle.Query().
		Where(jobtitle.ID(id), jobtitle.TenantID(tenantID)).
		Only(ctx)
}

func (s *Service) CreateJobTitle(ctx context.Context, tenantID uuid.UUID, in NamedInput) (*ent.JobTitle, error) {
	if in.Title == "" {
		return nil, fmt.Errorf("orgsettings: job title is required")
	}
	b := s.orm.JobTitle.Create().SetTenantID(tenantID).SetTitle(in.Title)
	if in.Description != "" {
		b = b.SetDescription(in.Description)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateJobTitle(ctx context.Context, tenantID, id uuid.UUID, in NamedInput) (*ent.JobTitle, error) {
	if _, err := s.GetJobTitle(ctx, tenantID, id); err != nil {
		return nil, err
	}
	u := s.orm.JobTitle.UpdateOneID(id)
	if in.Title != "" {
		u = u.SetTitle(in.Title)
	}
	if in.Description != "" {
		u = u.SetDescription(in.Description)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteJobTitle(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.JobTitle.Delete().
		Where(jobtitle.ID(id), jobtitle.TenantID(tenantID)).
		Exec(ctx)
	if err != nil {
		return fmt.Errorf("orgsettings: delete job title: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("orgsettings: job title not found")
	}
	return nil
}

// ---- Job groups ----

func (s *Service) ListJobGroups(ctx context.Context, tenantID uuid.UUID) ([]*ent.JobGroup, error) {
	return s.orm.JobGroup.Query().
		Where(jobgroup.TenantID(tenantID)).
		Order(ent.Asc(jobgroup.FieldTitle)).
		All(ctx)
}

func (s *Service) GetJobGroup(ctx context.Context, tenantID, id uuid.UUID) (*ent.JobGroup, error) {
	return s.orm.JobGroup.Query().
		Where(jobgroup.ID(id), jobgroup.TenantID(tenantID)).
		Only(ctx)
}

func (s *Service) CreateJobGroup(ctx context.Context, tenantID uuid.UUID, in NamedInput) (*ent.JobGroup, error) {
	if in.Title == "" {
		return nil, fmt.Errorf("orgsettings: job group title is required")
	}
	b := s.orm.JobGroup.Create().SetTenantID(tenantID).SetTitle(in.Title)
	if in.Description != "" {
		b = b.SetDescription(in.Description)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateJobGroup(ctx context.Context, tenantID, id uuid.UUID, in NamedInput) (*ent.JobGroup, error) {
	if _, err := s.GetJobGroup(ctx, tenantID, id); err != nil {
		return nil, err
	}
	u := s.orm.JobGroup.UpdateOneID(id)
	if in.Title != "" {
		u = u.SetTitle(in.Title)
	}
	if in.Description != "" {
		u = u.SetDescription(in.Description)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteJobGroup(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.JobGroup.Delete().
		Where(jobgroup.ID(id), jobgroup.TenantID(tenantID)).
		Exec(ctx)
	if err != nil {
		return fmt.Errorf("orgsettings: delete job group: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("orgsettings: job group not found")
	}
	return nil
}
