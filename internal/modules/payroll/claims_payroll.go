package payroll

import (
	"context"
	"fmt"
	"time"

	"entgo.io/ent/dialect/sql"
	"entgo.io/ent/dialect/sql/sqljson"
	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/expenseclaim"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// Approved expense claims are paid through payroll. A taxable claim is a taxable earning on the
// payslip. A non-taxable claim stays out of gross and PAYE and is added to net pay; treasury
// booked it to 2600 Employee Reimbursements Payable on approval and clears that account from the
// erp.payroll.processed totals.reimbursements figure. A claim treasury settles on its own
// (treasury.claim.settled) is paid and no run picks it up.
// A claim is linked to the payslip that carries it (metadata payroll_period and payslip_id),
// so it is paid once: a re-run of the same period picks it up again and relinks it, another
// period skips it, and it is marked paid when that payslip's net pay is dispatched.
const (
	claimMetaPeriod  = "payroll_period"
	claimMetaPayslip = "payslip_id"
	claimEarningCode = "expense_claim"
)

// loadPayrollClaims returns, per employee, the approved and unpaid claims (taxable or not) dated
// on or before the end of the period that are not already linked to another period's payslip.
func (s *Service) loadPayrollClaims(ctx context.Context, tenantID uuid.UUID, period time.Time, emps []*ent.Employee) (map[uuid.UUID][]*ent.ExpenseClaim, error) {
	ids := make([]uuid.UUID, len(emps))
	for i, e := range emps {
		ids[i] = e.ID
	}
	out := map[uuid.UUID][]*ent.ExpenseClaim{}
	if len(ids) == 0 {
		return out, nil
	}
	month := time.Date(period.Year(), period.Month(), 1, 0, 0, 0, 0, time.UTC)
	end := month.AddDate(0, 1, 0)
	rows, err := s.orm.ExpenseClaim.Query().Where(
		expenseclaim.TenantID(tenantID),
		expenseclaim.EmployeeIDIn(ids...),
		expenseclaim.Approved(true),
		expenseclaim.IsPaid(false),
		expenseclaim.DeleteStatus(false),
		expenseclaim.Or(expenseclaim.ApplicationDateIsNil(), expenseclaim.ApplicationDateLT(end)),
	).All(ctx)
	if err != nil {
		return nil, fmt.Errorf("payroll: load expense claims: %w", err)
	}
	key := month.Format("2006-01")
	for _, c := range rows {
		if linked, _ := c.Metadata[claimMetaPeriod].(string); linked != "" && linked != key {
			continue
		}
		out[c.EmployeeID] = append(out[c.EmployeeID], c)
	}
	return out, nil
}

// applyClaims adds an employee's taxable claims to taxable gross and their non-taxable claims to
// net pay, and lists each on the payslip. A per diem claim is non-taxable only up to the daily
// tax-free limit times its days (Income Tax Act s.5(2)(a)(iii)): the rest is taxed. The claim is
// still paid in full as a reimbursement (treasury booked all of it to reimbursements payable), so
// the excess is added to taxable pay only.
func applyClaims(claims []*ent.ExpenseClaim, dailyExempt decimal.Decimal, in *payrollengine.EmployeeInput, items *EmployeeItemized) {
	for _, c := range claims {
		if !c.Amount.IsPositive() {
			continue
		}
		label := "Expense claim"
		if c.ClaimType != "" {
			label = "Expense claim (" + c.ClaimType + ")"
		}
		if c.Taxable {
			in.TaxableAllowances = in.TaxableAllowances.Add(c.Amount)
			items.Earnings = append(items.Earnings, EarningLine{Code: claimEarningCode, Label: label, Amount: c.Amount})
		} else {
			in.Reimbursements = in.Reimbursements.Add(c.Amount)
			items.Reimbursements = append(items.Reimbursements, LabeledAmount{Label: label, Amount: c.Amount})
			if excess := perDiemTaxable(c, dailyExempt); excess.IsPositive() {
				in.TaxableOnly = in.TaxableOnly.Add(excess)
				items.PerDiemTaxable = append(items.PerDiemTaxable, LabeledAmount{Label: "Per diem above the tax-free limit", Amount: excess})
			}
		}
		items.ClaimIDs = append(items.ClaimIDs, c.ID)
	}
}

// perDiemTaxable is the part of a per diem claim above the tax-free limit for its days. A claim
// without a day count, or no limit configured, has no taxable part.
func perDiemTaxable(c *ent.ExpenseClaim, dailyExempt decimal.Decimal) decimal.Decimal {
	if c.ClaimType != "per_diem" || !dailyExempt.IsPositive() {
		return decimal.Zero
	}
	var days decimal.Decimal
	switch v := c.Metadata["days"].(type) {
	case float64:
		days = decimal.NewFromFloat(v)
	case string:
		days, _ = decimal.NewFromString(v)
	}
	if !days.IsPositive() {
		return decimal.Zero
	}
	return decimal.Max(decimal.Zero, c.Amount.Sub(dailyExempt.Mul(days))).Round(2)
}

// linkClaimsToPayslip records which payslip carries each claim.
func (s *Service) linkClaimsToPayslip(ctx context.Context, tenantID, payslipID uuid.UUID, period time.Time, ids []uuid.UUID) error {
	if len(ids) == 0 {
		return nil
	}
	rows, err := s.orm.ExpenseClaim.Query().Where(expenseclaim.TenantID(tenantID), expenseclaim.IDIn(ids...),
		expenseclaim.IsPaid(false)).All(ctx)
	if err != nil {
		return err
	}
	for _, c := range rows {
		meta := map[string]any{}
		for k, v := range c.Metadata {
			meta[k] = v
		}
		meta[claimMetaPeriod] = period.Format("2006-01")
		meta[claimMetaPayslip] = payslipID.String()
		if err := c.Update().SetMetadata(meta).SetScheduleToPayroll(true).Exec(ctx); err != nil {
			return err
		}
	}
	return nil
}

// markClaimsPaid marks the claims carried by the given payslips as paid.
func markClaimsPaid(ctx context.Context, c *ent.Client, tenantID uuid.UUID, payslipIDs []uuid.UUID) error {
	if len(payslipIDs) == 0 {
		return nil
	}
	vals := make([]any, len(payslipIDs))
	for i, id := range payslipIDs {
		vals[i] = id.String()
	}
	_, err := c.ExpenseClaim.Update().Where(
		expenseclaim.TenantID(tenantID),
		expenseclaim.IsPaid(false),
		func(s *sql.Selector) {
			s.Where(sqljson.ValueIn(s.C(expenseclaim.FieldMetadata), vals, sqljson.Path(claimMetaPayslip)))
		},
	).SetIsPaid(true).SetPaymentDate(time.Now().UTC()).Save(ctx)
	if err != nil {
		return fmt.Errorf("payroll: mark claims paid: %w", err)
	}
	return nil
}
