// Package employees implements tenant-isolated HR employee management (the FK hub).
package employees

import (
	"context"
	"fmt"
	"strings"

	entsql "entgo.io/ent/dialect/sql"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/authtenant"
	"github.com/Bengo-Hub/erp-api/internal/ent/customuser"
	"github.com/Bengo-Hub/erp-api/internal/ent/employee"
	"github.com/Bengo-Hub/erp-api/internal/ent/employeebankaccount"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
)

// blankOrNull matches a string column that is NULL or empty (junk placeholder rows
// from the legacy migration stored NULL, not ""), so the predicate must cover both.
func blankOrNull(col string) func(*entsql.Selector) {
	return func(s *entsql.Selector) {
		s.Where(entsql.Or(entsql.IsNull(s.C(col)), entsql.EQ(s.C(col), "")))
	}
}

// StaffNumberer issues a tenant-scoped staff number (SLUG/YYYY/### from the document-sequence
// service). Kept as a minimal interface so employees doesn't import the docs/sequence package.
type StaffNumberer interface {
	GenerateEmployeeNumber(ctx context.Context, tenantID uuid.UUID, slug string) (string, error)
}

// Service holds employee CRUD + derived-field recomputation. Every query is filtered by
// tenant_id; callers pass the tenant from the request scope (gaps §2 isolation).
type Service struct {
	orm *ent.Client
	seq StaffNumberer // optional; when set, blank staff numbers are auto-issued as SLUG/YYYY/###
}

func NewService(orm *ent.Client) *Service { return &Service{orm: orm} }

// WithSequence wires the staff-number generator so new employees get a meaningful number.
func (s *Service) WithSequence(seq StaffNumberer) *Service {
	s.seq = seq
	return s
}

// tenantSlug resolves the tenant's slug (used as the staff-number prefix). Blank on lookup failure.
func (s *Service) tenantSlug(ctx context.Context, tenantID uuid.UUID) string {
	if at, err := s.orm.AuthTenant.Query().Where(authtenant.ID(tenantID)).Only(ctx); err == nil {
		return at.Slug
	}
	return ""
}

// nextStaffNumber returns a generated staff number, or "" when no generator is wired.
func (s *Service) nextStaffNumber(ctx context.Context, tenantID uuid.UUID) string {
	if s.seq == nil {
		return ""
	}
	if n, err := s.seq.GenerateEmployeeNumber(ctx, tenantID, s.tenantSlug(ctx, tenantID)); err == nil {
		return n
	}
	return ""
}

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

// ErrNameRequired is returned by Create when first_name or last_name is blank. The HTTP
// layer maps it to 400 validation_failed (this is what allowed the blank placeholder rows).
var ErrNameRequired = fmt.Errorf("first_name and last_name are required")

// Create inserts a tenant-scoped employee.
func (s *Service) Create(ctx context.Context, tenantID uuid.UUID, in CreateInput) (*ent.Employee, error) {
	if strings.TrimSpace(in.FirstName) == "" || strings.TrimSpace(in.LastName) == "" {
		return nil, ErrNameRequired
	}
	// Auto-issue a meaningful staff number (SLUG/YYYY/###) when the caller didn't supply one.
	if strings.TrimSpace(in.EmployeeNumber) == "" {
		in.EmployeeNumber = s.nextStaffNumber(ctx, tenantID)
	}
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

// UpsertFromAuthUser projects an auth-api user into an erp Employee, keyed (verifiable)
// on the auth user id. It is idempotent: re-running updates the same row rather than
// creating duplicates. Steps:
//  1. resolve/create the erp CustomUser shadow for this auth user (keyed on external_id =
//     authUserID), mirroring rbac.EnsureUserFromToken's provisioning;
//  2. find the employee by user_id == customUser.id (the CustomUser shadow id) and upsert
//     name/email/outlet, generating a stable employee_number when none exists.
//
// isPlatformAdmin lets the caller skip projecting the platform superuser (the global
// codevertexitsolutions.com owner) into a tenant's employee roster — see the guard below.
func (s *Service) UpsertFromAuthUser(ctx context.Context, tenantID, authUserID uuid.UUID, email, fullName string, outletID *uuid.UUID, isPlatformAdmin bool) (*ent.Employee, error) {
	if tenantID == uuid.Nil || authUserID == uuid.Nil {
		return nil, fmt.Errorf("employees: upsert-from-auth requires tenant_id and auth_user_id")
	}
	// Guard: never turn the PLATFORM owner/superuser into a tenant employee. The caller
	// passes isPlatformAdmin (heuristic: platform email domain AND a superuser/admin role).
	if isPlatformAdmin {
		return nil, nil
	}

	cu, err := s.ensureCustomUser(ctx, tenantID, authUserID, email, fullName)
	if err != nil {
		return nil, err
	}

	first, last := splitName(fullName)

	existing, err := s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.UserID(cu.ID)).
		First(ctx)
	if ent.IsNotFound(err) {
		b := s.orm.Employee.Create().
			SetTenantID(tenantID).
			SetUserID(cu.ID).
			SetFirstName(first).
			SetLastName(last).
			SetEmail(email).
			SetEmployeeNumber(employeeNumberFromEmail(email, authUserID))
		if outletID != nil {
			b = b.SetOutletID(*outletID)
		}
		return b.Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("employees: upsert lookup: %w", err)
	}

	upd := existing.Update()
	if first != "" {
		upd = upd.SetFirstName(first)
	}
	if last != "" {
		upd = upd.SetLastName(last)
	}
	if email != "" {
		upd = upd.SetEmail(email)
	}
	if outletID != nil {
		upd = upd.SetOutletID(*outletID)
	}
	if existing.EmployeeNumber == nil || *existing.EmployeeNumber == "" {
		upd = upd.SetEmployeeNumber(employeeNumberFromEmail(email, authUserID))
	}
	return upd.Save(ctx)
}

// ensureCustomUser resolves the erp CustomUser shadow keyed on external_id (= auth user id),
// creating it if absent. Mirrors rbac.EnsureUserFromToken's provisioning (without role
// reconciliation, which the auth.user consumer/backfill does not need).
func (s *Service) ensureCustomUser(ctx context.Context, tenantID, authUserID uuid.UUID, email, fullName string) (*ent.CustomUser, error) {
	externalID := authUserID.String()
	first, last := splitName(fullName)

	u, err := s.orm.CustomUser.Query().
		Where(customuser.ExternalID(externalID)).
		Only(ctx)
	if ent.IsNotFound(err) {
		// CustomUser.email is NotEmpty in the schema; fall back to a stable placeholder.
		if strings.TrimSpace(email) == "" {
			email = externalID + "@unknown.local"
		}
		return s.orm.CustomUser.Create().
			SetTenantID(tenantID).
			SetExternalID(externalID).
			SetEmail(email).
			SetFirstName(first).
			SetLastName(last).
			Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("employees: query custom_user: %w", err)
	}
	upd := u.Update()
	if email != "" && email != u.Email {
		upd = upd.SetEmail(email)
	}
	if first != "" {
		upd = upd.SetFirstName(first)
	}
	if last != "" {
		upd = upd.SetLastName(last)
	}
	if u.TenantID == uuid.Nil && tenantID != uuid.Nil {
		upd = upd.SetTenantID(tenantID)
	}
	return upd.Save(ctx)
}

// SoftDeleteBlankPlaceholders soft-deletes keyless junk employees for a tenant: rows with no
// SSO link (user_id IS NULL) AND empty first_name/last_name/email. Returns the count deleted.
// Used by the one-time backfill after projecting real auth users (cmd/sync-employees).
func (s *Service) SoftDeleteBlankPlaceholders(ctx context.Context, tenantID uuid.UUID) (int, error) {
	return s.orm.Employee.Update().
		Where(
			employee.TenantID(tenantID),
			employee.UserIDIsNil(),
			employee.Deleted(false),
			blankOrNull(employee.FieldFirstName),
			blankOrNull(employee.FieldLastName),
		).
		SetDeleted(true).
		Save(ctx)
}

// splitName splits a full name on the first space: first token = first_name, the remainder
// (trimmed) = last_name. "Jane" -> ("Jane",""); "Jane Mary Doe" -> ("Jane","Mary Doe").
func splitName(full string) (first, last string) {
	full = strings.TrimSpace(full)
	if full == "" {
		return "", ""
	}
	if i := strings.IndexByte(full, ' '); i >= 0 {
		return strings.TrimSpace(full[:i]), strings.TrimSpace(full[i+1:])
	}
	return full, ""
}

// RenumberEmployees re-issues clean staff numbers (SLUG/YYYY/###) to every active employee in the
// tenant, in creation order. Cosmetic + safe — payslips/contracts reference the employee UUID, not
// the number. Returns the count updated.
func (s *Service) RenumberEmployees(ctx context.Context, tenantID uuid.UUID) (int, error) {
	if s.seq == nil {
		return 0, fmt.Errorf("employees: staff-number generator not configured")
	}
	emps, err := s.orm.Employee.Query().
		Where(employee.TenantID(tenantID), employee.Deleted(false)).
		Order(ent.Asc(employee.FieldCreatedAt)).All(ctx)
	if err != nil {
		return 0, err
	}
	slug := s.tenantSlug(ctx, tenantID)
	n := 0
	for _, e := range emps {
		num, gerr := s.seq.GenerateEmployeeNumber(ctx, tenantID, slug)
		if gerr != nil {
			return n, gerr
		}
		if _, uerr := e.Update().SetEmployeeNumber(num).Save(ctx); uerr != nil {
			return n, uerr
		}
		n++
	}
	return n, nil
}

// employeeNumberFromEmail derives a stable employee number from the email local-part, falling
// back to a short slice of the auth user id when the email has no usable local-part. Stable so
// re-running the backfill/consumer does not churn the value.
func employeeNumberFromEmail(email string, authUserID uuid.UUID) string {
	local := email
	if i := strings.IndexByte(email, '@'); i > 0 {
		local = email[:i]
	}
	local = strings.TrimSpace(local)
	if local != "" {
		return "EMP-" + strings.ToUpper(local)
	}
	return "EMP-" + strings.ToUpper(strings.ReplaceAll(authUserID.String(), "-", "")[:8])
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
// SalaryReliefInput carries the per-employee salary extras captured on the salary form: the KRA
// relief amounts plus the preferred net-pay disbursement channel. Zero-value = no relief and
// default (bank_transfer) payout — backward-compatible with callers that don't set them.
type SalaryReliefInput struct {
	InsurancePremium    decimal.Decimal
	PensionContribution decimal.Decimal
	MortgageInterest    decimal.Decimal
	DisabilityExempt    bool
	// PreferredPayoutMethod: bank_transfer | mpesa_b2c | airtel | paystack_mobile | cash.
	PreferredPayoutMethod string
	PayoutPhone           string // MSISDN for mobile-money channels
}

func (s *Service) UpsertSalary(ctx context.Context, tenantID, employeeID uuid.UUID, monthly decimal.Decimal, payMode, incomeTax, currency string, reliefs SalaryReliefInput) (*ent.SalaryDetails, error) {
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
	payoutMethod := reliefs.PreferredPayoutMethod
	if payoutMethod == "" {
		payoutMethod = "bank_transfer"
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
			SetInsurancePremium(reliefs.InsurancePremium).
			SetPensionContribution(reliefs.PensionContribution).
			SetMortgageInterest(reliefs.MortgageInterest).
			SetDisabilityExempt(reliefs.DisabilityExempt).
			SetPreferredPayoutMethod(payoutMethod).
			SetPayoutPhone(reliefs.PayoutPhone).
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
		SetInsurancePremium(reliefs.InsurancePremium).
		SetPensionContribution(reliefs.PensionContribution).
		SetMortgageInterest(reliefs.MortgageInterest).
		SetDisabilityExempt(reliefs.DisabilityExempt).
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
