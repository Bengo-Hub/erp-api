// Package contracts implements tenant-isolated employment-contract CRUD
// (/hrm/contracts). Duration is recomputed from start/end on write (data-migration §4).
package contracts

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/contract"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
)

// Service holds contract CRUD. Every query is tenant-filtered.
type Service struct {
	orm *ent.Client
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// List returns tenant-scoped contracts (optionally filtered by employee), newest first.
func (s *Service) List(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID, limit, offset int) ([]*ent.Contract, int, error) {
	q := s.orm.Contract.Query().Where(contract.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(contract.EmployeeID(*employeeID))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("contracts: count: %w", err)
	}
	if limit <= 0 || limit > 200 {
		limit = 50
	}
	rows, err := q.Order(ent.Desc(contract.FieldCreatedAt)).Limit(limit).Offset(offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("contracts: list: %w", err)
	}
	return rows, total, nil
}

func (s *Service) Get(ctx context.Context, tenantID, id uuid.UUID) (*ent.Contract, error) {
	return s.orm.Contract.Query().
		Where(contract.ID(id), contract.TenantID(tenantID)).
		Only(ctx)
}

// Input is the create/update payload for a contract.
type Input struct {
	EmployeeID   uuid.UUID
	ContractType string
	StartDate    *time.Time
	EndDate      *time.Time
	Salary       decimal.Decimal
	Status       string
}

// durationMonths recomputes whole months between start and end (rounded down).
func durationMonths(start, end *time.Time) int {
	if start == nil || end == nil || end.Before(*start) {
		return 0
	}
	months := (end.Year()-start.Year())*12 + int(end.Month()) - int(start.Month())
	if end.Day() < start.Day() {
		months--
	}
	if months < 0 {
		months = 0
	}
	return months
}

func (s *Service) Create(ctx context.Context, tenantID uuid.UUID, in Input) (*ent.Contract, error) {
	// Validate the employee belongs to the tenant.
	if exists, err := s.orm.Employee.Query().
		Where(employee.ID(in.EmployeeID), employee.TenantID(tenantID)).Exist(ctx); err != nil {
		return nil, fmt.Errorf("contracts: employee check: %w", err)
	} else if !exists {
		return nil, fmt.Errorf("contracts: employee not found for tenant")
	}
	b := s.orm.Contract.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetSalary(in.Salary).
		SetDurationMonths(durationMonths(in.StartDate, in.EndDate))
	if in.ContractType != "" {
		b = b.SetContractType(in.ContractType)
	}
	if in.Status != "" {
		b = b.SetStatus(in.Status)
	}
	if in.StartDate != nil {
		b = b.SetStartDate(*in.StartDate)
	}
	if in.EndDate != nil {
		b = b.SetEndDate(*in.EndDate)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("contracts: create: %w", err)
	}
	return row, nil
}

func (s *Service) Update(ctx context.Context, tenantID, id uuid.UUID, in Input) (*ent.Contract, error) {
	existing, err := s.Get(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	start := existing.StartDate
	end := existing.EndDate
	u := existing.Update()
	if in.ContractType != "" {
		u = u.SetContractType(in.ContractType)
	}
	if in.Status != "" {
		u = u.SetStatus(in.Status)
	}
	if in.StartDate != nil {
		u = u.SetStartDate(*in.StartDate)
		start = in.StartDate
	}
	if in.EndDate != nil {
		u = u.SetEndDate(*in.EndDate)
		end = in.EndDate
	}
	if !in.Salary.IsZero() {
		u = u.SetSalary(in.Salary)
	}
	u = u.SetDurationMonths(durationMonths(start, end))
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("contracts: update: %w", err)
	}
	return row, nil
}

func (s *Service) Delete(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.Contract.Delete().
		Where(contract.ID(id), contract.TenantID(tenantID)).
		Exec(ctx)
	if err != nil {
		return fmt.Errorf("contracts: delete: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("contracts: not found")
	}
	return nil
}

// EmployeeName resolves "First Last" + employee_number for the contract's employee
// (best-effort; empty on miss). Used to enrich list/detail responses for erp-ui.
func (s *Service) EmployeeName(ctx context.Context, tenantID, employeeID uuid.UUID) (name, number string) {
	emp, err := s.orm.Employee.Query().
		Where(employee.ID(employeeID), employee.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return "", ""
	}
	name = emp.FirstName
	if emp.LastName != "" {
		if name != "" {
			name += " "
		}
		name += emp.LastName
	}
	if emp.EmployeeNumber != nil {
		number = *emp.EmployeeNumber
	}
	return name, number
}
