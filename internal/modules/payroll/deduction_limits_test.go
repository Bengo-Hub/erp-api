package payroll

import (
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// The engine's applied amounts replace the wanted installments on the payslip lines and the
// frozen recovery lines; what was cut shows as a deferred line and stays on the balance.
func TestCapRecoveries(t *testing.T) {
	dd := decimal.RequireFromString
	loanA, loanB, adv := uuid.New(), uuid.New(), uuid.New()
	in := payrollengine.EmployeeInput{
		Loans: []payrollengine.Recoverable{
			{Installment: dd("100"), Outstanding: dd("0")}, // settled: never itemised
			{Installment: dd("5000"), Outstanding: dd("9000")},
			{Installment: dd("8000"), Outstanding: dd("8000")},
		},
		Advances: []payrollengine.Recoverable{{Installment: dd("2000"), Outstanding: dd("2000")}},
	}
	items := EmployeeItemized{
		Loans:    []LabeledAmount{{Label: "Loan", Amount: dd("5000")}, {Label: "Loan", Amount: dd("8000")}},
		Advances: []LabeledAmount{{Label: "Salary Advance", Amount: dd("2000")}},
		Recoveries: []RecoveryAlloc{
			{Type: "loan", ID: loanA, Amount: dd("5000")},
			{Type: "loan", ID: loanB, Amount: dd("8000")},
			{Type: "advance", ID: adv, Amount: dd("2000")},
		},
	}
	res := payrollengine.PayslipResult{
		LoansApplied:    []decimal.Decimal{dd("0"), dd("5000"), dd("1500")},
		AdvancesApplied: []decimal.Decimal{dd("2000")},
	}
	capRecoveries(in, res, &items)

	if len(items.Loans) != 2 || !items.Loans[1].Amount.Equal(dd("1500")) {
		t.Fatalf("loans = %+v, want 5000 and 1500", items.Loans)
	}
	if !items.Recoveries[1].Amount.Equal(dd("1500")) || items.Recoveries[1].ID != loanB || !items.Recoveries[2].Amount.Equal(dd("2000")) {
		t.Errorf("recoveries = %+v", items.Recoveries)
	}
	if len(items.Deferred) != 1 || !items.Deferred[0].Amount.Equal(dd("6500")) || items.Deferred[0].Code != "loan" {
		t.Fatalf("deferred = %+v, want one loan line of 6500", items.Deferred)
	}

	// A recovery cut to nothing leaves no deduction line, only the deferred one.
	items.Loans = []LabeledAmount{{Label: "Loan", Amount: dd("5000")}, {Label: "Loan", Amount: dd("8000")}}
	items.Recoveries[1].Amount = dd("8000")
	items.Deferred = nil
	res.LoansApplied = []decimal.Decimal{dd("0"), dd("5000"), dd("0")}
	capRecoveries(in, res, &items)
	if len(items.Loans) != 1 || !items.Recoveries[1].Amount.IsZero() || !items.Deferred[0].Amount.Equal(dd("8000")) {
		t.Errorf("cut to zero: loans %+v recoveries %+v deferred %+v", items.Loans, items.Recoveries, items.Deferred)
	}
	lines := composeLines(dd("10000"), res, items)
	found := false
	for _, l := range lines {
		if l.Section == secShortfall && l.Code == "loan" && l.Cash.Equal(dd("8000")) {
			found = true
		}
	}
	if !found {
		t.Errorf("no deferred loan line in %+v", lines)
	}
}
