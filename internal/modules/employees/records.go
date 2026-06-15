package employees

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/customuser"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeedisciplinary"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeeeducation"
	"github.com/Bengo-Hub/erp-api/internal/ent/employmenthistory"
)

// EmployeeIDForExternalUser resolves the caller's OWN employee id from their SSO subject
// (JWT sub → CustomUser shadow by external_id → Employee by user_id). Used by ESS
// (mine=true) so an employee sees only their own leave/payslips without HR permissions.
func (s *Service) EmployeeIDForExternalUser(ctx context.Context, tenantID uuid.UUID, externalID string) (uuid.UUID, bool) {
	if externalID == "" {
		return uuid.Nil, false
	}
	cu, err := s.orm.CustomUser.Query().Where(customuser.ExternalID(externalID)).Only(ctx)
	if err != nil {
		return uuid.Nil, false
	}
	emp, err := s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.UserID(cu.ID), employee.Deleted(false)).
		First(ctx)
	if err != nil {
		return uuid.Nil, false
	}
	return emp.ID, true
}

// records.go — CRUD for the HR-owned employee sub-records (education, employment
// history, disciplinary). All tenant + employee scoped; mirrors subresources.go.

// ---- Education ----

type EducationInput struct {
	EmployeeID     uuid.UUID
	Institution    string
	Qualification  string
	FieldOfStudy   string
	Grade          string
	CertificateURL string
	StartDate      *time.Time
	EndDate        *time.Time
}

func (s *Service) ListEducation(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.EmployeeEducation, error) {
	q := s.orm.EmployeeEducation.Query().Where(employeeeducation.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(employeeeducation.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(employeeeducation.FieldEndDate)).All(ctx)
}

func (s *Service) CreateEducation(ctx context.Context, tenantID uuid.UUID, in EducationInput) (*ent.EmployeeEducation, error) {
	if err := s.ownsEmployee(ctx, tenantID, in.EmployeeID); err != nil {
		return nil, err
	}
	b := s.orm.EmployeeEducation.Create().
		SetTenantID(tenantID).SetEmployeeID(in.EmployeeID).SetInstitution(in.Institution)
	if in.Qualification != "" {
		b = b.SetQualification(in.Qualification)
	}
	if in.FieldOfStudy != "" {
		b = b.SetFieldOfStudy(in.FieldOfStudy)
	}
	if in.Grade != "" {
		b = b.SetGrade(in.Grade)
	}
	if in.CertificateURL != "" {
		b = b.SetCertificateURL(in.CertificateURL)
	}
	if in.StartDate != nil {
		b = b.SetStartDate(*in.StartDate)
	}
	if in.EndDate != nil {
		b = b.SetEndDate(*in.EndDate)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateEducation(ctx context.Context, tenantID, id uuid.UUID, in EducationInput) (*ent.EmployeeEducation, error) {
	existing, err := s.orm.EmployeeEducation.Query().
		Where(employeeeducation.ID(id), employeeeducation.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := existing.Update()
	if in.Institution != "" {
		u = u.SetInstitution(in.Institution)
	}
	if in.Qualification != "" {
		u = u.SetQualification(in.Qualification)
	}
	if in.FieldOfStudy != "" {
		u = u.SetFieldOfStudy(in.FieldOfStudy)
	}
	if in.Grade != "" {
		u = u.SetGrade(in.Grade)
	}
	if in.CertificateURL != "" {
		u = u.SetCertificateURL(in.CertificateURL)
	}
	if in.StartDate != nil {
		u = u.SetStartDate(*in.StartDate)
	}
	if in.EndDate != nil {
		u = u.SetEndDate(*in.EndDate)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteEducation(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.EmployeeEducation.Delete().
		Where(employeeeducation.ID(id), employeeeducation.TenantID(tenantID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("employees: delete education: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("employees: education record not found")
	}
	return nil
}

// ---- Employment history ----

type EmploymentHistoryInput struct {
	EmployeeID       uuid.UUID
	Employer         string
	Designation      string
	ReasonForLeaving string
	StartDate        *time.Time
	EndDate          *time.Time
}

func (s *Service) ListEmploymentHistory(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.EmploymentHistory, error) {
	q := s.orm.EmploymentHistory.Query().Where(employmenthistory.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(employmenthistory.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(employmenthistory.FieldEndDate)).All(ctx)
}

func (s *Service) CreateEmploymentHistory(ctx context.Context, tenantID uuid.UUID, in EmploymentHistoryInput) (*ent.EmploymentHistory, error) {
	if err := s.ownsEmployee(ctx, tenantID, in.EmployeeID); err != nil {
		return nil, err
	}
	b := s.orm.EmploymentHistory.Create().
		SetTenantID(tenantID).SetEmployeeID(in.EmployeeID).SetEmployer(in.Employer)
	if in.Designation != "" {
		b = b.SetDesignation(in.Designation)
	}
	if in.ReasonForLeaving != "" {
		b = b.SetReasonForLeaving(in.ReasonForLeaving)
	}
	if in.StartDate != nil {
		b = b.SetStartDate(*in.StartDate)
	}
	if in.EndDate != nil {
		b = b.SetEndDate(*in.EndDate)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateEmploymentHistory(ctx context.Context, tenantID, id uuid.UUID, in EmploymentHistoryInput) (*ent.EmploymentHistory, error) {
	existing, err := s.orm.EmploymentHistory.Query().
		Where(employmenthistory.ID(id), employmenthistory.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := existing.Update()
	if in.Employer != "" {
		u = u.SetEmployer(in.Employer)
	}
	if in.Designation != "" {
		u = u.SetDesignation(in.Designation)
	}
	if in.ReasonForLeaving != "" {
		u = u.SetReasonForLeaving(in.ReasonForLeaving)
	}
	if in.StartDate != nil {
		u = u.SetStartDate(*in.StartDate)
	}
	if in.EndDate != nil {
		u = u.SetEndDate(*in.EndDate)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteEmploymentHistory(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.EmploymentHistory.Delete().
		Where(employmenthistory.ID(id), employmenthistory.TenantID(tenantID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("employees: delete employment history: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("employees: employment history not found")
	}
	return nil
}

// ---- Disciplinary ----

type DisciplinaryInput struct {
	EmployeeID   uuid.UUID
	Category     string
	Description  string
	ActionTaken  string
	Status       string
	DocumentURL  string
	IncidentDate *time.Time
}

func (s *Service) ListDisciplinary(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.EmployeeDisciplinary, error) {
	q := s.orm.EmployeeDisciplinary.Query().Where(employeedisciplinary.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(employeedisciplinary.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(employeedisciplinary.FieldIncidentDate)).All(ctx)
}

func (s *Service) CreateDisciplinary(ctx context.Context, tenantID uuid.UUID, in DisciplinaryInput) (*ent.EmployeeDisciplinary, error) {
	if err := s.ownsEmployee(ctx, tenantID, in.EmployeeID); err != nil {
		return nil, err
	}
	b := s.orm.EmployeeDisciplinary.Create().
		SetTenantID(tenantID).SetEmployeeID(in.EmployeeID)
	if in.Category != "" {
		b = b.SetCategory(in.Category)
	}
	if in.Description != "" {
		b = b.SetDescription(in.Description)
	}
	if in.ActionTaken != "" {
		b = b.SetActionTaken(in.ActionTaken)
	}
	if in.Status != "" {
		b = b.SetStatus(in.Status)
	}
	if in.DocumentURL != "" {
		b = b.SetDocumentURL(in.DocumentURL)
	}
	if in.IncidentDate != nil {
		b = b.SetIncidentDate(*in.IncidentDate)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateDisciplinary(ctx context.Context, tenantID, id uuid.UUID, in DisciplinaryInput) (*ent.EmployeeDisciplinary, error) {
	existing, err := s.orm.EmployeeDisciplinary.Query().
		Where(employeedisciplinary.ID(id), employeedisciplinary.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := existing.Update()
	if in.Category != "" {
		u = u.SetCategory(in.Category)
	}
	if in.Description != "" {
		u = u.SetDescription(in.Description)
	}
	if in.ActionTaken != "" {
		u = u.SetActionTaken(in.ActionTaken)
	}
	if in.Status != "" {
		u = u.SetStatus(in.Status)
	}
	if in.DocumentURL != "" {
		u = u.SetDocumentURL(in.DocumentURL)
	}
	if in.IncidentDate != nil {
		u = u.SetIncidentDate(*in.IncidentDate)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteDisciplinary(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.EmployeeDisciplinary.Delete().
		Where(employeedisciplinary.ID(id), employeedisciplinary.TenantID(tenantID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("employees: delete disciplinary: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("employees: disciplinary record not found")
	}
	return nil
}
