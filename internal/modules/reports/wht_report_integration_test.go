package reports

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/consultantvoucher"
)

// The withholding tax report sums approved and paid consultant vouchers of the period per payee,
// residency and rate, and leaves out drafts, deleted vouchers, other periods and other tenants.
func TestIntegration_WithholdingTaxReport(t *testing.T) {
	client := analyticsClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	d := decimal.RequireFromString
	oct := time.Date(2026, 10, 1, 0, 0, 0, 0, time.UTC)

	a := client.Employee.Create().SetTenantID(tenant).SetFirstName("Amina").SetPinNo("A001").SaveX(ctx)
	b := client.Employee.Create().SetTenantID(tenant).SetFirstName("Brian").SaveX(ctx)
	voucher := func(emp uuid.UUID, tenantID uuid.UUID, resident bool, rate, gross string, st consultantvoucher.Status, period time.Time, deleted bool) {
		g, r := d(gross), d(rate)
		wht := g.Mul(r).Round(2)
		client.ConsultantVoucher.Create().SetTenantID(tenantID).SetEmployeeID(emp).SetIsResident(resident).
			SetWhtRate(r).SetGrossAmount(g).SetWhtAmount(wht).SetNetAmount(g.Sub(wht)).
			SetStatus(st).SetPeriod(period).SetDeleteStatus(deleted).SaveX(ctx)
	}
	voucher(a.ID, tenant, true, "0.05", "10000", consultantvoucher.StatusApproved, oct, false)
	voucher(a.ID, tenant, true, "0.05", "20000", consultantvoucher.StatusPaid, oct, false)
	voucher(b.ID, tenant, false, "0.20", "5000", consultantvoucher.StatusPaid, oct, false)
	voucher(a.ID, tenant, true, "0.05", "99999", consultantvoucher.StatusDraft, oct, false)
	voucher(a.ID, tenant, true, "0.05", "99999", consultantvoucher.StatusPaid, oct, true)
	voucher(a.ID, tenant, true, "0.05", "99999", consultantvoucher.StatusPaid, oct.AddDate(0, 1, 0), false)
	voucher(a.ID, uuid.New(), true, "0.05", "99999", consultantvoucher.StatusPaid, oct, false)

	f, err := ResolvePeriod(2026, 10, nil)
	if err != nil {
		t.Fatal(err)
	}
	rep, err := NewService(client).WithholdingTax(ctx, tenant, f)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 2 {
		t.Fatalf("rows = %v, want one per payee and rate", rep.Rows)
	}
	first, second := rep.Rows[0], rep.Rows[1]
	if first["payee_name"] != "Amina" || first["payee_pin"] != "A001" || first["residency"] != "Resident" ||
		first["gross_amount"] != "30000.00" || first["withholding_tax"] != "1500.00" ||
		first["net_payment"] != "28500.00" || first["withholding_rate"] != "5" || first["vouchers"] != 2 {
		t.Fatalf("resident row = %v", first)
	}
	if second["residency"] != "Non-resident" || second["withholding_tax"] != "1000.00" || second["withholding_rate"] != "20" {
		t.Fatalf("non-resident row = %v", second)
	}
	if rep.Totals["withholding_tax"] != "2500.00" || rep.Totals["gross_amount"] != "35000.00" {
		t.Fatalf("totals = %v", rep.Totals)
	}
}
