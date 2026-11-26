package payroll

import (
	"testing"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// Per diem above 10,000 a day is taxed; the claim is still paid in full as a reimbursement.
func TestPerDiemAboveTheLimit(t *testing.T) {
	dec := decimal.RequireFromString
	claims := []*ent.ExpenseClaim{
		{ClaimType: "per_diem", Amount: dec("36000"), Metadata: map[string]any{"days": float64(3)}},  // 6,000 over
		{ClaimType: "per_diem", Amount: dec("18000"), Metadata: map[string]any{"days": float64(2)}},  // within
		{ClaimType: "per_diem", Amount: dec("15000")},                                                // no day count
		{ClaimType: "reimbursement", Amount: dec("50000"), Metadata: map[string]any{"days": float64(1)}}, // not per diem
	}
	var in payrollengine.EmployeeInput
	var items EmployeeItemized
	applyClaims(claims, dec("10000"), &in, &items)
	if !in.TaxableOnly.Equal(dec("6000")) || !in.Reimbursements.Equal(dec("119000")) {
		t.Errorf("taxable-only %s reimbursements %s, want 6000 and 119000", in.TaxableOnly, in.Reimbursements)
	}
	var none payrollengine.EmployeeInput
	applyClaims(claims, decimal.Zero, &none, &EmployeeItemized{})
	if !none.TaxableOnly.IsZero() {
		t.Errorf("no limit configured, taxable-only %s", none.TaxableOnly)
	}
}
