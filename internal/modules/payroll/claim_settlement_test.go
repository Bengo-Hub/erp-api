package payroll

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// A treasury voucher settles a claim once; its reversal reopens only that settlement, and
// another tenant's event never touches the claim.
func TestIntegration_TreasuryClaimSettlement(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	svc := NewService(client, nil)
	tenant := uuid.New()
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Asha").SaveX(ctx)
	claim := client.ExpenseClaim.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetApproved(true).
		SetAmount(decimal.NewFromInt(900)).SetMetadata(map[string]any{"source": "erp"}).SaveX(ctx)
	in := TreasurySettlement{Amount: "900.00", Currency: "KES", VoucherNumber: "PV-0007", Reference: "MPESA123"}

	if _, err := svc.SettleClaimByTreasury(ctx, uuid.New(), claim.ID, in); !ent.IsNotFound(err) {
		t.Fatalf("other tenant: err = %v, want not found", err)
	}
	out, err := svc.SettleClaimByTreasury(ctx, tenant, claim.ID, in)
	if err != nil || out != ClaimSettleApplied {
		t.Fatalf("settle = %s, %v", out, err)
	}
	c := client.ExpenseClaim.GetX(ctx, claim.ID)
	if !c.IsPaid || c.PaymentDate == nil || c.Metadata["source"] != "erp" || c.Metadata[claimMetaTreasury] == nil {
		t.Fatalf("settled claim = %+v", c)
	}
	if out, _ := svc.SettleClaimByTreasury(ctx, tenant, claim.ID, in); out != ClaimSettleNoop {
		t.Fatalf("redelivered settle = %s, want noop", out)
	}
	// A settled claim is never carried into a payroll run.
	got, _ := svc.loadPayrollClaims(ctx, tenant, c.CreatedAt, []*ent.Employee{emp})
	if len(got[emp.ID]) != 0 {
		t.Fatalf("settled claim picked up by payroll")
	}

	out, err = svc.ReverseClaimTreasurySettlement(ctx, tenant, claim.ID)
	if err != nil || out != ClaimSettleApplied {
		t.Fatalf("reverse = %s, %v", out, err)
	}
	c = client.ExpenseClaim.GetX(ctx, claim.ID)
	if c.IsPaid || c.PaymentDate != nil || c.Metadata[claimMetaTreasury] != nil || c.Metadata["source"] != "erp" {
		t.Fatalf("reversed claim = %+v", c)
	}
	if out, _ := svc.ReverseClaimTreasurySettlement(ctx, tenant, claim.ID); out != ClaimSettleNoop {
		t.Fatalf("redelivered reverse = %s, want noop", out)
	}

	// A claim paid through a payslip stays paid when a treasury reversal arrives.
	payslipPaid := client.ExpenseClaim.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetApproved(true).
		SetAmount(decimal.NewFromInt(500)).SetIsPaid(true).SaveX(ctx)
	if out, _ := svc.ReverseClaimTreasurySettlement(ctx, tenant, payslipPaid.ID); out != ClaimSettleNoop {
		t.Fatalf("reverse of a payroll-paid claim = %s, want noop", out)
	}
	if !client.ExpenseClaim.GetX(ctx, payslipPaid.ID).IsPaid {
		t.Fatal("payroll-paid claim reopened by a treasury reversal")
	}

	// Settling a claim an unpaid payslip carries is reported so the period can be re-run.
	carried := client.ExpenseClaim.Create().SetTenantID(tenant).SetEmployeeID(emp.ID).SetApproved(true).
		SetAmount(decimal.NewFromInt(300)).SetMetadata(map[string]any{claimMetaPayslip: uuid.NewString()}).SaveX(ctx)
	if out, _ := svc.SettleClaimByTreasury(ctx, tenant, carried.ID, in); out != ClaimSettleCarried {
		t.Fatalf("settle of a payslip-carried claim = %s, want carried_by_payslip", out)
	}
}
