package payroll

import (
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Non-taxable claims carried in net pay are reported as totals.reimbursements, and deductions
// are what was withheld: gross + reimbursements - net. Treasury derives statutory the same way.
func TestBuildPayrollEventReimbursements(t *testing.T) {
	a := &ent.Payslip{ID: uuid.New(), EmployeeID: uuid.New(), GrossPay: dec("50000"), NetPay: dec("40900"), Paye: dec("8000")}
	b := &ent.Payslip{ID: uuid.New(), EmployeeID: uuid.New(), GrossPay: dec("30000"), NetPay: dec("25000")}
	p := DisburseParams{TenantID: uuid.New(), Period: time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)}
	reimb := map[uuid.UUID]decimal.Decimal{a.ID: dec("900")}

	payload, net := buildPayrollEvent([]*ent.Payslip{a, b}, nil, nil, reimb, p, "ref")
	if !net.Equal(dec("65900")) {
		t.Fatalf("net = %s, want 65900", net)
	}
	tot := payload["totals"].(map[string]any)
	if tot["reimbursements"] != "900.00" || tot["gross"] != "80000.00" || tot["net"] != "65900.00" || tot["deductions"] != "15000.00" {
		t.Fatalf("totals = %v", tot)
	}
	lines := payload["lines"].([]map[string]any)
	if lines[0]["reimbursements"] != "900.00" {
		t.Fatalf("line reimbursements = %v, want 900.00", lines[0]["reimbursements"])
	}
	if _, ok := lines[1]["reimbursements"]; ok {
		t.Fatalf("a payslip without reimbursements carries the key")
	}

	// No reimbursements: the key is still sent, as zero.
	payload, _ = buildPayrollEvent([]*ent.Payslip{b}, nil, nil, nil, p, "ref")
	if got := payload["totals"].(map[string]any)["reimbursements"]; got != "0.00" {
		t.Fatalf("reimbursements without claims = %v, want 0.00", got)
	}
}
