package employees

import (
	"context"
	"fmt"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/jobgroup"
	"github.com/Bengo-Hub/erp-api/internal/ent/salarydetails"
	"github.com/Bengo-Hub/erp-api/internal/modules/inherited"
)

// SalaryInput is the salary form. Nil leaves a stored value unchanged, so saving one field never
// resets another (reliefs, payout channel, job group).
type SalaryInput struct {
	Monthly   *decimal.Decimal
	PayMode   *string // pay frequency: monthly | weekly | daily
	IncomeTax *string
	Currency  *string
	// KRA relief amounts (actual monthly figures; the engine applies the caps).
	InsurancePremium    *decimal.Decimal
	PensionContribution *decimal.Decimal
	MortgageInterest    *decimal.Decimal
	DisabilityExempt    *bool
	// PreferredPayoutMethod: bank_transfer | mpesa_b2c | airtel | paystack_mobile | cash.
	PreferredPayoutMethod *string
	PayoutPhone           *string
	// JobGroupID sets the job group; a pointer to uuid.Nil clears it.
	JobGroupID *uuid.UUID
	// EffectiveFrom schedules the change from a month (this month or later). Nil changes the
	// salary in force now.
	EffectiveFrom *time.Time
}

// Empty reports whether the input changes nothing.
func (in SalaryInput) Empty() bool { return in == SalaryInput{} }

// SalaryView is the stored salary as the salary form reads it.
type SalaryView struct {
	BasicSalary           string     `json:"basic_salary"`
	PayFrequency          string     `json:"pay_frequency"`
	IncomeTax             string     `json:"income_tax"`
	Currency              string     `json:"currency"`
	InsurancePremium      string     `json:"insurance_premium"`
	PensionContribution   string     `json:"pension_contribution"`
	MortgageInterest      string     `json:"mortgage_interest"`
	DisabilityExempt      bool       `json:"disability_exempt"`
	PreferredPayoutMethod string     `json:"preferred_payout_method"`
	PayoutPhone           string     `json:"payout_phone"`
	JobGroupID            *uuid.UUID `json:"job_group_id,omitempty"`
	// EffectiveFrom is the month the salary shown started (empty: from the beginning).
	EffectiveFrom string `json:"effective_from,omitempty"`
	// Scheduled are later salaries already set, each from its month.
	Scheduled []ScheduledSalary `json:"scheduled"`
}

// ScheduledSalary is a salary set to start in a later month.
type ScheduledSalary struct {
	EffectiveFrom string `json:"effective_from"`
	BasicSalary   string `json:"basic_salary"`
}

// payFrequencies are the pay_mode values that are a pay frequency. Older rows may hold a payment
// method there (bank, mpesa) from a form that mixed the two up; those read as monthly.
var payFrequencies = map[string]bool{"monthly": true, "weekly": true, "daily": true, "perhour": true, "perday": true}

// activeSalary is the row in force now (see SalaryInForce), else the newest row (a scheduled or
// not yet activated salary).
func (s *Service) activeSalary(ctx context.Context, tenantID, employeeID uuid.UUID) (*ent.SalaryDetails, error) {
	rows, err := s.salaryRows(ctx, tenantID, employeeID)
	if err != nil {
		return nil, err
	}
	if r := SalaryInForce(rows, time.Now().UTC()); r != nil {
		return r, nil
	}
	if len(rows) == 0 {
		return nil, &ent.NotFoundError{}
	}
	return rows[0], nil
}

// salaryRows are an employee's salary rows, newest first.
func (s *Service) salaryRows(ctx context.Context, tenantID, employeeID uuid.UUID) ([]*ent.SalaryDetails, error) {
	return s.orm.SalaryDetails.Query().
		Where(salarydetails.TenantID(tenantID), salarydetails.EmployeeID(employeeID)).
		Order(ent.Desc(salarydetails.FieldCreatedAt)).All(ctx)
}

// scheduledSalaryRow returns the row a salary change from month applies to: the row already
// starting that month, else a new row starting then, copied from the salary in force that month,
// so earlier months keep what they paid. A month before the current one is refused.
func (s *Service) scheduledSalaryRow(ctx context.Context, tenantID, employeeID uuid.UUID, month time.Time) (*ent.SalaryDetails, error) {
	month = time.Date(month.Year(), month.Month(), 1, 0, 0, 0, 0, time.UTC)
	now := time.Now().UTC()
	if month.Before(time.Date(now.Year(), now.Month(), 1, 0, 0, 0, 0, time.UTC)) {
		return nil, fmt.Errorf("a salary change starts this month or later: months already paid keep their salary")
	}
	rows, err := s.salaryRows(ctx, tenantID, employeeID)
	if err != nil {
		return nil, err
	}
	for _, r := range rows {
		if r.EffectiveFrom != nil && r.EffectiveFrom.Equal(month) {
			return r, nil
		}
	}
	c := s.orm.SalaryDetails.Create().SetTenantID(tenantID).SetEmployeeID(employeeID).SetEffectiveFrom(month).
		SetPayMode("monthly").SetMonthlySalary(decimal.Zero).SetIsActive(false)
	if base := SalaryInForce(rows, MonthEnd(month)); base != nil {
		c = c.SetPayMode(base.PayMode).SetIncomeTax(base.IncomeTax).SetCurrency(base.Currency).
			SetMonthlySalary(base.MonthlySalary).SetHourlyRate(base.HourlyRate).SetDailyRate(base.DailyRate).
			SetInsurancePremium(base.InsurancePremium).SetPensionContribution(base.PensionContribution).
			SetMortgageInterest(base.MortgageInterest).SetDisabilityExempt(base.DisabilityExempt).
			SetNillableBankAccountID(base.BankAccountID).SetPreferredPayoutMethod(base.PreferredPayoutMethod).
			SetPayoutPhone(base.PayoutPhone).SetNillableJobGroupID(base.JobGroupID).
			SetNillableWorkersUnionID(base.WorkersUnionID).SetIsActive(true)
	}
	return c.Save(ctx)
}

// Salary returns the employee's stored salary, or nil when none is set.
func (s *Service) Salary(ctx context.Context, tenantID, employeeID uuid.UUID) (*SalaryView, error) {
	sd, err := s.activeSalary(ctx, tenantID, employeeID)
	if ent.IsNotFound(err) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	v := &SalaryView{
		BasicSalary: sd.MonthlySalary.StringFixed(2), PayFrequency: sd.PayMode, IncomeTax: sd.IncomeTax,
		Currency: sd.Currency, InsurancePremium: sd.InsurancePremium.StringFixed(2),
		PensionContribution: sd.PensionContribution.StringFixed(2), MortgageInterest: sd.MortgageInterest.StringFixed(2),
		DisabilityExempt: sd.DisabilityExempt, PreferredPayoutMethod: sd.PreferredPayoutMethod,
		PayoutPhone: sd.PayoutPhone, JobGroupID: sd.JobGroupID,
	}
	if !payFrequencies[v.PayFrequency] {
		v.PayFrequency = "monthly"
	}
	if sd.EffectiveFrom != nil {
		v.EffectiveFrom = sd.EffectiveFrom.Format("2006-01")
	}
	v.Scheduled = []ScheduledSalary{}
	rows, err := s.salaryRows(ctx, tenantID, employeeID)
	if err != nil {
		return nil, err
	}
	now := time.Now().UTC()
	for i := len(rows) - 1; i >= 0; i-- { // oldest first
		r := rows[i]
		if r.IsActive && r.EffectiveFrom != nil && r.EffectiveFrom.After(now) {
			v.Scheduled = append(v.Scheduled, ScheduledSalary{EffectiveFrom: r.EffectiveFrom.Format("2006-01"), BasicSalary: r.MonthlySalary.StringFixed(2)})
		}
	}
	return v, nil
}

// CheckSalary validates the input without saving.
func (s *Service) CheckSalary(ctx context.Context, tenantID uuid.UUID, in SalaryInput) error {
	if in.Empty() {
		return nil
	}
	for name, v := range map[string]*decimal.Decimal{"basic salary": in.Monthly, "insurance premium": in.InsurancePremium,
		"pension contribution": in.PensionContribution, "mortgage interest": in.MortgageInterest} {
		if v != nil && v.IsNegative() {
			return fmt.Errorf("%s cannot be negative", name)
		}
	}
	if in.JobGroupID != nil && *in.JobGroupID != uuid.Nil {
		ok, err := s.orm.JobGroup.Query().Where(jobgroup.ID(*in.JobGroupID), jobgroup.TenantIDIn(inherited.Tenants(s.systemTenant, tenantID)...)).Exist(ctx)
		if err != nil {
			return err
		}
		if !ok {
			return fmt.Errorf("job group not found")
		}
	}
	return nil
}

// UpsertSalary sets or updates an employee's salary details, the one place the job group lives.
// Hourly and daily rates are derived from the monthly salary, never taken from the caller. A job
// group set before any salary is kept on an inactive row, so payroll still reports the missing
// salary instead of paying zero; setting the salary activates the same row.
func (s *Service) UpsertSalary(ctx context.Context, tenantID, employeeID uuid.UUID, in SalaryInput) (*ent.SalaryDetails, error) {
	if _, err := s.Get(ctx, tenantID, employeeID); err != nil {
		return nil, fmt.Errorf("employees: salary owner: %w", err)
	}
	if err := s.CheckSalary(ctx, tenantID, in); err != nil {
		return nil, err
	}
	var row *ent.SalaryDetails
	var err error
	if in.EffectiveFrom != nil {
		row, err = s.scheduledSalaryRow(ctx, tenantID, employeeID, *in.EffectiveFrom)
		if err != nil {
			return nil, err
		}
	} else {
		row, err = s.activeSalary(ctx, tenantID, employeeID)
	}
	if ent.IsNotFound(err) {
		row, err = s.orm.SalaryDetails.Create().SetTenantID(tenantID).SetEmployeeID(employeeID).
			SetPayMode("monthly").SetMonthlySalary(decimal.Zero).SetIsActive(false).Save(ctx)
	}
	if err != nil {
		return nil, fmt.Errorf("employees: salary lookup: %w", err)
	}
	u := row.Update()
	if in.Monthly != nil {
		hourly, daily := decimal.Zero, decimal.Zero
		if in.Monthly.IsPositive() {
			hourly = in.Monthly.DivRound(hoursPerMonth, 4)
			daily = in.Monthly.DivRound(daysPerMonth, 4)
		}
		u = u.SetMonthlySalary(*in.Monthly).SetHourlyRate(hourly).SetDailyRate(daily).SetIsActive(true)
	}
	text := func(v *string, set func(string)) {
		if v != nil && strings.TrimSpace(*v) != "" {
			set(strings.TrimSpace(*v))
		}
	}
	text(in.PayMode, func(v string) { u = u.SetPayMode(v) })
	text(in.IncomeTax, func(v string) { u = u.SetIncomeTax(v) })
	text(in.Currency, func(v string) { u = u.SetCurrency(v) })
	text(in.PreferredPayoutMethod, func(v string) { u = u.SetPreferredPayoutMethod(v) })
	if in.PayoutPhone != nil {
		u = u.SetPayoutPhone(strings.TrimSpace(*in.PayoutPhone)) // "" clears it
	}
	if in.InsurancePremium != nil {
		u = u.SetInsurancePremium(*in.InsurancePremium)
	}
	if in.PensionContribution != nil {
		u = u.SetPensionContribution(*in.PensionContribution)
	}
	if in.MortgageInterest != nil {
		u = u.SetMortgageInterest(*in.MortgageInterest)
	}
	if in.DisabilityExempt != nil {
		u = u.SetDisabilityExempt(*in.DisabilityExempt)
	}
	if in.JobGroupID != nil {
		if *in.JobGroupID == uuid.Nil {
			u = u.ClearJobGroupID()
		} else {
			u = u.SetJobGroupID(*in.JobGroupID)
		}
	}
	return u.Save(ctx)
}
