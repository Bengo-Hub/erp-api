package payroll

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/pieceoutput"
)

func TestPieceAmount(t *testing.T) {
	d := decimal.RequireFromString
	if got := pieceAmount(d("120"), d("20"), d("15.5")); !got.Equal(d("1550")) {
		t.Fatalf("amount %s, want 1550", got)
	}
	if got := pieceAmount(d("5"), d("9"), d("10")); !got.IsZero() {
		t.Fatalf("more rejects than output pays nothing, got %s", got)
	}
}

// Output is recorded at the rate in effect, reviewed, and only approved output of the month
// reaches the run; paying it links it to the payslip.
func TestIntegration_PieceOutputFlow(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	svc := NewService(client, nil)
	tenant := uuid.New()
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("Akinyi").SetNationalID("77").SaveX(ctx)
	code, name, unit := "PICK", "Tea picking", "kg"
	rate := decimal.RequireFromString("12")
	from := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	pr, err := svc.CreatePieceRate(ctx, tenant, PieceRateInput{Code: &code, Name: &name, Unit: &unit, Rate: &rate, EffectiveFrom: &from})
	if err != nil || pr.Currency == "" {
		t.Fatalf("rate %+v err %v", pr, err)
	}
	if _, err := svc.CreatePieceOutput(ctx, tenant, PieceOutputInput{EmployeeID: emp.ID, PieceRateID: pr.ID,
		Date: time.Date(2026, 10, 30, 0, 0, 0, 0, time.UTC), Quantity: decimal.NewFromInt(10)}); err != ErrPieceRateInactive {
		t.Fatalf("output before the rate starts: %v", err)
	}
	day := time.Date(2026, 11, 20, 0, 0, 0, 0, time.UTC)
	a, err := svc.CreatePieceOutput(ctx, tenant, PieceOutputInput{EmployeeID: emp.ID, PieceRateID: pr.ID, Date: day,
		Quantity: decimal.NewFromInt(50), RejectedQuantity: decimal.NewFromInt(5)})
	if err != nil || !a.Amount.Equal(decimal.NewFromInt(540)) || a.PieceRateName != name {
		t.Fatalf("output %+v err %v", a, err)
	}
	b, _ := svc.CreatePieceOutput(ctx, tenant, PieceOutputInput{EmployeeID: emp.ID, PieceRateID: pr.ID, Date: day, Quantity: decimal.NewFromInt(10)})
	if n, err := svc.ReviewPieceOutputs(ctx, tenant, nil, []uuid.UUID{a.ID}, "approve"); err != nil || n != 1 {
		t.Fatalf("approve %d %v", n, err)
	}
	if n, _ := svc.ReviewPieceOutputs(ctx, tenant, nil, []uuid.UUID{b.ID}, "reject"); n != 1 {
		t.Fatal("reject failed")
	}
	got, err := svc.approvedPieceOutputs(ctx, tenant, day)
	if err != nil || len(got[emp.ID]) != 1 {
		t.Fatalf("approved output %v err %v", got, err)
	}
	slip := uuid.New()
	if err := svc.markPieceOutputsPaid(ctx, tenant, slip, []uuid.UUID{a.ID}); err != nil {
		t.Fatal(err)
	}
	if o := client.PieceOutput.GetX(ctx, a.ID); o.Status != pieceoutput.StatusPaid || o.PayslipID == nil || *o.PayslipID != slip {
		t.Fatalf("paid output %+v", o)
	}
	if n, _ := svc.ReviewPieceOutputs(ctx, tenant, nil, []uuid.UUID{a.ID}, "reject"); n != 0 {
		t.Fatal("paid output must not be reviewed again")
	}
}
