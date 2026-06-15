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

func (s *Service) DeleteDepartment(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.Department.Delete().
		Where(department.ID(id), department.TenantID(tenantID)).
		Exec(ctx)
	if err != nil {
		return fmt.Errorf("orgsettings: delete department: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("orgsettings: department not found")
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
