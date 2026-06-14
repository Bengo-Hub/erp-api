// Package employees implements tenant-isolated HR employee management (the FK hub).
package employees

import (
	"context"
	"fmt"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebankaccount"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
)

// Service holds employee CRUD + derived-field recomputation. Every query is filtered by
// tenant_id; callers pass the tenant from the request scope (gaps §2 isolation).
type Service struct {
	orm *ent.Client
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// hoursPerMonth / daysPerMonth are the divisors for derived rate recomputation
// (recompute on write — never trust stored values; data-migration §4).
var (
	hoursPerMonth = decimal.NewFromInt(208) // 26 days * 8h
	daysPerMonth  = decimal.NewFromInt(26)
)

// ListParams filters an employee listing.
type ListParams struct {
	TenantID       uuid.UUID
	OutletID       uuid.UUID // uuid.Nil = all outlets
	IncludeDeleted bool
	Limit          int
	Offset         int
}

// List returns tenant-scoped employees (optionally outlet-scoped), excluding soft-deleted.
func (s *Service) List(ctx context.Context, p ListParams) ([]*ent.Employee, int, error) {
	q := s.orm.Employee.Query().Where(employee.TenantID(p.TenantID))
	if p.OutletID != uuid.Nil {
		q = q.Where(employee.OutletID(p.OutletID))
	}
	if !p.IncludeDeleted {
		q = q.Where(employee.Deleted(false))
	}
	total, err := q.Clone().Count(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("employees: count: %w", err)
	}
	if p.Limit <= 0 || p.Limit > 200 {
		p.Limit = 50
	}
	rows, err := q.Order(ent.Asc(employee.FieldCreatedAt)).
		Limit(p.Limit).Offset(p.Offset).All(ctx)
	if err != nil {
		return nil, 0, fmt.Errorf("employees: list: %w", err)
	}
	return rows, total, nil
}

// Get fetches one tenant-scoped employee.
func (s *Service) Get(ctx context.Context, tenantID, id uuid.UUID) (*ent.Employee, error) {
	return s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.ID(id)).
		Only(ctx)
}

// CreateInput is the payload for creating an employee.
type CreateInput struct {
	OutletID          *uuid.UUID
	UserID            *uuid.UUID
	EmployeeNumber    string
	FirstName         string
	LastName          string
	Email             string
	Gender            string
	NationalID        string
	PinNo             string
	ShifOrNhifNumber  string
	NssfNo            string
	ResidentialStatus string
}

// Create inserts a tenant-scoped employee.
func (s *Service) Create(ctx context.Context, tenantID uuid.UUID, in CreateInput) (*ent.Employee, error) {
	b := s.orm.Employee.Create().
		SetTenantID(tenantID).
		SetEmployeeNumber(in.EmployeeNumber).
		SetFirstName(in.FirstName).
		SetLastName(in.LastName).
		SetEmail(in.Email).
		SetGender(in.Gender).
		SetNationalID(in.NationalID).
		SetPinNo(in.PinNo).
		SetNssfNo(in.NssfNo).
		SetResidentialStatus(in.ResidentialStatus)
	if in.OutletID != nil {
		b = b.SetOutletID(*in.OutletID)
	}
	if in.UserID != nil {
		b = b.SetUserID(*in.UserID)
	}
	if in.ShifOrNhifNumber != "" {
		b = b.SetShifOrNhifNumber(in.ShifOrNhifNumber)
	}
	row, err := b.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("employees: create: %w", err)
	}
	return row, nil
}

// SoftDelete marks an employee deleted (tenant-scoped).
func (s *Service) SoftDelete(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.Employee.Update().
		Where(employee.TenantID(tenantID), employee.ID(id)).
		SetDeleted(true).Save(ctx)
	if err != nil {
		return fmt.Errorf("employees: delete: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("employees: not found")
	}
	return nil
}

// UpsertSalary sets/updates an employee's salary details and recomputes hourly/daily
// rates from monthly_salary (never trusting client-supplied derived values, §4).
func (s *Service) UpsertSalary(ctx context.Context, tenantID, employeeID uuid.UUID, monthly decimal.Decimal, payMode, incomeTax, currency string) (*ent.SalaryDetails, error) {
	if _, err := s.Get(ctx, tenantID, employeeID); err != nil {
		return nil, fmt.Errorf("employees: salary owner: %w", err)
	}
	hourly := decimal.Zero
	daily := decimal.Zero
	if monthly.GreaterThan(decimal.Zero) {
		hourly = monthly.DivRound(hoursPerMonth, 4)
		daily = monthly.DivRound(daysPerMonth, 4)
	}
	if incomeTax == "" {
		incomeTax = "primary"
	}
	if currency == "" {
		currency = "KES"
	}

	existing, err := s.orm.SalaryDetails.Query().
		Where(salarydetails.TenantID(tenantID), salarydetails.EmployeeID(employeeID)).
		First(ctx)
	if ent.IsNotFound(err) {
		return s.orm.SalaryDetails.Create().
			SetTenantID(tenantID).
			SetEmployeeID(employeeID).
			SetMonthlySalary(monthly).
			SetHourlyRate(hourly).
			SetDailyRate(daily).
			SetPayMode(payMode).
			SetIncomeTax(incomeTax).
			SetCurrency(currency).
			Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("employees: salary lookup: %w", err)
	}
	return existing.Update().
		SetMonthlySalary(monthly).
		SetHourlyRate(hourly).
		SetDailyRate(daily).
		SetPayMode(payMode).
		SetIncomeTax(incomeTax).
		SetCurrency(currency).
		Save(ctx)
}

// SetPrimaryBankAccount enforces "single primary per employee" atomically (port of
// EmployeeBankAccountViewSet): clears the flag on siblings, sets it on the target.
func (s *Service) SetPrimaryBankAccount(ctx context.Context, tenantID, employeeID, accountID uuid.UUID) error {
	tx, err := s.orm.Tx(ctx)
	if err != nil {
		return fmt.Errorf("employees: begin tx: %w", err)
	}
	defer func() { _ = tx.Rollback() }()

	if _, err := tx.EmployeeBankAccount.Update().
		Where(
			employeebankaccount.TenantID(tenantID),
			employeebankaccount.EmployeeID(employeeID),
		).SetIsPrimary(false).Save(ctx); err != nil {
		return fmt.Errorf("employees: clear primary: %w", err)
	}
	n, err := tx.EmployeeBankAccount.Update().
		Where(
			employeebankaccount.TenantID(tenantID),
			employeebankaccount.EmployeeID(employeeID),
			employeebankaccount.ID(accountID),
		).SetIsPrimary(true).Save(ctx)
	if err != nil {
		return fmt.Errorf("employees: set primary: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("employees: bank account not found for employee")
	}
	return tx.Commit()
}
