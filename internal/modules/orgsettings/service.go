// Package orgsettings implements tenant-isolated HR reference data CRUD:
// departments, job titles and job groups. These back the erp-ui HRM settings
// screens (/hrm/departments, /hrm/employees/job-titles, /hrm/employees/job-groups).
package orgsettings

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/department"
	"github.com/Bengo-Hub/erp-api/internal/ent/hrdetails"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobgroup"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobtitle"
)

// Service holds reference-data CRUD. Every query is tenant-filtered.
type Service struct {
	orm *ent.Client
	// systemTenant owns the platform's job groups every company inherits (jobgroups_inherit.go).
	systemTenant uuid.UUID
	costCenters  CostCenterSource // nil: cost centre ids are not checked
	log          *zap.Logger
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
	// CostCenterSet marks that the caller sent cost_center_id (departments only): CostCenterID
	// nil then clears the link, otherwise sets it.
	CostCenterSet bool
	CostCenterID  *uuid.UUID
	// Extra holds the sent values kept in the row's metadata (extra.go), by key; each kind keeps
	// only its own keys.
	Extra map[string]string
}

func (s *Service) CreateDepartment(ctx context.Context, tenantID uuid.UUID, in NamedInput) (*ent.Department, error) {
	if in.Title == "" {
		return nil, fmt.Errorf("orgsettings: department title is required")
	}
	if in.CostCenterSet {
		if err := s.checkCostCenter(ctx, tenantID, in.CostCenterID); err != nil {
			return nil, err
		}
	}
	b := s.orm.Department.Create().SetTenantID(tenantID).SetTitle(in.Title)
	if meta := mergeExtra(nil, in.Extra, departmentExtras); meta != nil {
		b = b.SetMetadata(meta)
	}
	if in.Code != "" {
		b = b.SetCode(in.Code)
	}
	if in.CostCenterSet && in.CostCenterID != nil {
		b = b.SetCostCenterID(*in.CostCenterID)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateDepartment(ctx context.Context, tenantID, id uuid.UUID, in NamedInput) (*ent.Department, error) {
	cur, err := s.GetDepartment(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	// Only a changed cost centre is checked, so saving a department whose cost centre was later
	// retired in treasury still works for its other fields.
	if in.CostCenterSet && in.CostCenterID != nil && (cur.CostCenterID == nil || *cur.CostCenterID != *in.CostCenterID) {
		if err := s.checkCostCenter(ctx, tenantID, in.CostCenterID); err != nil {
			return nil, err
		}
	}
	u := s.orm.Department.UpdateOneID(id)
	if in.Title != "" {
		u = u.SetTitle(in.Title)
	}
	if meta := mergeExtra(cur.Metadata, in.Extra, departmentExtras); meta != nil {
		u = u.SetMetadata(meta)
	} else {
		u = u.ClearMetadata()
	}
	if in.Code != "" {
		u = u.SetCode(in.Code)
	}
	if in.CostCenterSet {
		if in.CostCenterID != nil {
			u = u.SetCostCenterID(*in.CostCenterID)
		} else {
			u = u.ClearCostCenterID()
		}
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
	if meta := mergeExtra(nil, in.Extra, jobTitleExtras); meta != nil {
		b = b.SetMetadata(meta)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateJobTitle(ctx context.Context, tenantID, id uuid.UUID, in NamedInput) (*ent.JobTitle, error) {
	cur, err := s.GetJobTitle(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	u := s.orm.JobTitle.UpdateOneID(id)
	if in.Title != "" {
		u = u.SetTitle(in.Title)
	}
	if meta := mergeExtra(cur.Metadata, in.Extra, jobTitleExtras); meta != nil {
		u = u.SetMetadata(meta)
	} else {
		u = u.ClearMetadata()
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

// GetJobGroup loads one of the company's own job groups.
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
	if meta := mergeExtra(nil, in.Extra, jobGroupExtras); meta != nil {
		if err := checkSalaryRange(meta); err != nil {
			return nil, err
		}
		b = b.SetMetadata(meta)
	}
	return b.Save(ctx)
}

// UpdateJobGroup edits an own job group, or keeps the company's description for an inherited one.
func (s *Service) UpdateJobGroup(ctx context.Context, tenantID, id uuid.UUID, in NamedInput) (*JobGroupRow, error) {
	row, err := s.JobGroupRowByID(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	if row.Inherited {
		return s.customiseJobGroup(ctx, tenantID, row, in)
	}
	meta := mergeExtra(row.Metadata, in.Extra, jobGroupExtras)
	if err := checkSalaryRange(meta); err != nil {
		return nil, err
	}
	g, err := s.updateOwnJobGroup(id, in, meta).Save(ctx)
	if err != nil {
		return nil, err
	}
	return &JobGroupRow{JobGroup: g}, nil
}

func (s *Service) updateOwnJobGroup(id uuid.UUID, in NamedInput, meta map[string]any) *ent.JobGroupUpdateOne {
	u := s.orm.JobGroup.UpdateOneID(id)
	if in.Title != "" {
		u = u.SetTitle(in.Title)
	}
	if in.Description != "" {
		u = u.SetDescription(in.Description)
	}
	if meta != nil {
		u = u.SetMetadata(meta)
	} else {
		u = u.ClearMetadata()
	}
	return u
}

// DeleteJobGroup deletes an own job group; a platform one is refused.
func (s *Service) DeleteJobGroup(ctx context.Context, tenantID, id uuid.UUID) error {
	if row, err := s.JobGroupRowByID(ctx, tenantID, id); err == nil && row.Inherited {
		return ErrInheritedJobGroup
	}
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
