package employees

import (
	"context"
	"fmt"
	"time"

	"github.com/google/uuid"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebankaccount"
	"github.com/Bengo-Hub/erp-api/internal/ent/nextofkin"
	"github.com/Bengo-Hub/erp-api/internal/ent/workshift"
)

// This file adds employee edit + bank-account/next-of-kin management on top of the
// core employee CRUD. All queries are tenant-isolated.

// UpdateInput is the editable subset of employee attributes (PUT/PATCH).
type UpdateInput struct {
	FirstName         *string
	LastName          *string
	Email             *string
	Gender            *string
	NationalID        *string
	PinNo             *string
	ShifOrNhifNumber  *string
	NssfNo            *string
	ResidentialStatus *string
	// DateOfBirth sets the date of birth; a pointer to the zero time clears it.
	DateOfBirth    *time.Time
	EmployeeNumber *string
	Terminated        *bool
	IsDirector        *bool
	IsShareholder     *bool
	// WorkShiftID sets the standard work shift (the person's weekly working hours); a pointer to
	// uuid.Nil clears it. It must be one of the tenant's shifts.
	WorkShiftID *uuid.UUID
}

// Update edits a tenant-scoped employee. Only non-nil fields are applied.
func (s *Service) Update(ctx context.Context, tenantID, id uuid.UUID, in UpdateInput) (*ent.Employee, error) {
	current, err := s.Get(ctx, tenantID, id)
	if err != nil {
		return nil, err
	}
	u := s.orm.Employee.UpdateOneID(id)
	if in.FirstName != nil {
		u = u.SetFirstName(*in.FirstName)
	}
	if in.LastName != nil {
		u = u.SetLastName(*in.LastName)
	}
	if in.Email != nil {
		u = u.SetEmail(*in.Email)
	}
	if in.Gender != nil {
		u = u.SetGender(*in.Gender)
	}
	if in.NationalID != nil {
		u = u.SetNationalID(*in.NationalID)
	}
	if in.PinNo != nil {
		u = u.SetPinNo(*in.PinNo)
	}
	if in.ShifOrNhifNumber != nil {
		u = u.SetShifOrNhifNumber(*in.ShifOrNhifNumber)
	}
	if in.NssfNo != nil {
		u = u.SetNssfNo(*in.NssfNo)
	}
	if in.ResidentialStatus != nil {
		u = u.SetResidentialStatus(*in.ResidentialStatus)
	}
	if in.EmployeeNumber != nil {
		u = u.SetEmployeeNumber(*in.EmployeeNumber)
	}
	if in.DateOfBirth != nil {
		if in.DateOfBirth.IsZero() {
			u = u.ClearDateOfBirth()
		} else {
			u = u.SetDateOfBirth(*in.DateOfBirth)
		}
	}
	if in.Terminated != nil {
		u = u.SetTerminated(*in.Terminated)
		// Date the exit when the employee is terminated; a reinstatement clears it.
		switch {
		case *in.Terminated && !current.Terminated:
			u = u.SetTerminatedAt(time.Now())
		case !*in.Terminated && current.Terminated:
			u = u.ClearTerminatedAt()
		}
	}
	if in.IsDirector != nil {
		u = u.SetIsDirector(*in.IsDirector)
	}
	if in.IsShareholder != nil {
		u = u.SetIsShareholder(*in.IsShareholder)
	}
	if in.WorkShiftID != nil {
		if *in.WorkShiftID == uuid.Nil {
			u = u.ClearWorkShiftID()
		} else {
			ok, err := s.orm.WorkShift.Query().Where(workshift.ID(*in.WorkShiftID), workshift.TenantID(tenantID)).Exist(ctx)
			if err != nil {
				return nil, fmt.Errorf("employees: work shift check: %w", err)
			}
			if !ok {
				return nil, fmt.Errorf("employees: work shift not found for tenant")
			}
			u = u.SetWorkShiftID(*in.WorkShiftID)
		}
	}
	row, err := u.Save(ctx)
	if err != nil {
		return nil, fmt.Errorf("employees: update: %w", err)
	}
	return row, nil
}

func (s *Service) ownsEmployee(ctx context.Context, tenantID, employeeID uuid.UUID) error {
	ok, err := s.orm.Employee.Query().Where(employee.ID(employeeID), employee.TenantID(tenantID)).Exist(ctx)
	if err != nil {
		return fmt.Errorf("employees: owner check: %w", err)
	}
	if !ok {
		return fmt.Errorf("employees: employee not found for tenant")
	}
	return nil
}

// ---- Bank accounts ----

func (s *Service) ListBankAccounts(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.EmployeeBankAccount, error) {
	q := s.orm.EmployeeBankAccount.Query().Where(employeebankaccount.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(employeebankaccount.EmployeeID(*employeeID))
	}
	return q.Order(ent.Desc(employeebankaccount.FieldIsPrimary)).All(ctx)
}

// BankAccountInput is the create/update payload for a bank account.
type BankAccountInput struct {
	EmployeeID    uuid.UUID
	BankName      string
	BranchName    string
	AccountName   string
	AccountNumber string
	IsPrimary     bool
}

func (s *Service) CreateBankAccount(ctx context.Context, tenantID uuid.UUID, in BankAccountInput) (*ent.EmployeeBankAccount, error) {
	if err := s.ownsEmployee(ctx, tenantID, in.EmployeeID); err != nil {
		return nil, err
	}
	b := s.orm.EmployeeBankAccount.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetAccountName(in.AccountName).
		SetAccountNumber(in.AccountNumber).
		SetIsPrimary(in.IsPrimary)
	if in.BankName != "" {
		b = b.SetBankName(in.BankName)
	}
	if in.BranchName != "" {
		b = b.SetBranchName(in.BranchName)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateBankAccount(ctx context.Context, tenantID, id uuid.UUID, in BankAccountInput) (*ent.EmployeeBankAccount, error) {
	existing, err := s.orm.EmployeeBankAccount.Query().
		Where(employeebankaccount.ID(id), employeebankaccount.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := existing.Update()
	if in.BankName != "" {
		u = u.SetBankName(in.BankName)
	}
	if in.BranchName != "" {
		u = u.SetBranchName(in.BranchName)
	}
	if in.AccountName != "" {
		u = u.SetAccountName(in.AccountName)
	}
	if in.AccountNumber != "" {
		u = u.SetAccountNumber(in.AccountNumber)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteBankAccount(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.EmployeeBankAccount.Delete().
		Where(employeebankaccount.ID(id), employeebankaccount.TenantID(tenantID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("employees: delete bank account: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("employees: bank account not found")
	}
	return nil
}

// ---- Next of kin ----

func (s *Service) ListNextOfKin(ctx context.Context, tenantID uuid.UUID, employeeID *uuid.UUID) ([]*ent.NextOfKin, error) {
	q := s.orm.NextOfKin.Query().Where(nextofkin.TenantID(tenantID))
	if employeeID != nil {
		q = q.Where(nextofkin.EmployeeID(*employeeID))
	}
	return q.Order(ent.Asc(nextofkin.FieldFullName)).All(ctx)
}

// NextOfKinInput is the create/update payload for a kin record.
type NextOfKinInput struct {
	EmployeeID   uuid.UUID
	FullName     string
	Relationship string
	Phone        string
	Email        string
	Address      string
}

func (s *Service) CreateNextOfKin(ctx context.Context, tenantID uuid.UUID, in NextOfKinInput) (*ent.NextOfKin, error) {
	if err := s.ownsEmployee(ctx, tenantID, in.EmployeeID); err != nil {
		return nil, err
	}
	b := s.orm.NextOfKin.Create().
		SetTenantID(tenantID).
		SetEmployeeID(in.EmployeeID).
		SetFullName(in.FullName)
	if in.Relationship != "" {
		b = b.SetRelationship(in.Relationship)
	}
	if in.Phone != "" {
		b = b.SetPhone(in.Phone)
	}
	if in.Email != "" {
		b = b.SetEmail(in.Email)
	}
	if in.Address != "" {
		b = b.SetAddress(in.Address)
	}
	return b.Save(ctx)
}

func (s *Service) UpdateNextOfKin(ctx context.Context, tenantID, id uuid.UUID, in NextOfKinInput) (*ent.NextOfKin, error) {
	existing, err := s.orm.NextOfKin.Query().
		Where(nextofkin.ID(id), nextofkin.TenantID(tenantID)).Only(ctx)
	if err != nil {
		return nil, err
	}
	u := existing.Update()
	if in.FullName != "" {
		u = u.SetFullName(in.FullName)
	}
	if in.Relationship != "" {
		u = u.SetRelationship(in.Relationship)
	}
	if in.Phone != "" {
		u = u.SetPhone(in.Phone)
	}
	if in.Email != "" {
		u = u.SetEmail(in.Email)
	}
	if in.Address != "" {
		u = u.SetAddress(in.Address)
	}
	return u.Save(ctx)
}

func (s *Service) DeleteNextOfKin(ctx context.Context, tenantID, id uuid.UUID) error {
	n, err := s.orm.NextOfKin.Delete().
		Where(nextofkin.ID(id), nextofkin.TenantID(tenantID)).Exec(ctx)
	if err != nil {
		return fmt.Errorf("employees: delete next of kin: %w", err)
	}
	if n == 0 {
		return fmt.Errorf("employees: next of kin not found")
	}
	return nil
}
