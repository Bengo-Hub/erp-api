package payrollsettings

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
)

// SHIF's KES 300 minimum is configuration on the platform SHIF formula: the deploy seeds it once,
// every tenant inherits it, a customised copy keeps it, and a platform change reaches tenants.
func TestIntegration_SHIFMinimumInherited(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	svc := NewService(client, uuid.New())
	seedPlatform(t, ctx, svc) // formulas without a minimum, as deployed before this change
	tenant := uuid.New()
	d := decimal.RequireFromString

	n, err := EnsureSHIFMinimum(ctx, client, svc.SystemTenant())
	if err != nil || n != 1 {
		t.Fatalf("first ensure = %d, %v; want 1", n, err)
	}
	if n, _ := EnsureSHIFMinimum(ctx, client, svc.SystemTenant()); n != 0 {
		t.Fatalf("second ensure = %d, want 0 (idempotent)", n)
	}

	res := netPay(t, ctx, svc, tenant, payrollengine.EmployeeInput{GrossPay: d("8000"), TaxCategory: "primary"})
	if !res.SHIFOrNHIF.Equal(d("300")) {
		t.Fatalf("inherited SHIF on 8,000 = %s, want 300", res.SHIFOrNHIF)
	}

	platform := client.PayrollFormula.Query().Where(payrollformula.TenantID(svc.SystemTenant()),
		payrollformula.CategoryEQ("shif"), payrollformula.IsCurrent(true)).OnlyX(ctx)

	// A tenant that customises SHIF keeps the minimum on its own copy.
	other := uuid.New()
	own, err := svc.CustomiseFormula(ctx, other, platform.ID)
	if err != nil {
		t.Fatal(err)
	}
	if m := FormulaMinimumContribution(own); !m.Equal(d("300")) {
		t.Fatalf("customised SHIF minimum = %s, want 300", m)
	}

	// The platform owner lowers the minimum: tenants that did not customise follow, and the deploy
	// does not put the old value back.
	items, _ := svc.FormulaItems(ctx, svc.SystemTenant(), platform.ID)
	in := FormulaInput{ID: &platform.ID, Type: platform.Type, Category: platform.Category, Title: platform.Title,
		EffectiveFrom: platform.EffectiveFrom, IsCurrent: true, MinimumContribution: decPtr(d("250"))}
	for _, it := range items {
		in.Items = append(in.Items, FormulaItemInput{AmountFrom: it.AmountFrom, AmountTo: it.AmountTo, DeductAmount: it.DeductAmount, DeductPercentage: it.DeductPercentage})
	}
	if _, err := svc.UpsertFormula(ctx, svc.SystemTenant(), in); err != nil {
		t.Fatal(err)
	}
	if n, _ := EnsureSHIFMinimum(ctx, client, svc.SystemTenant()); n != 0 {
		t.Fatalf("ensure after a platform change = %d, want 0", n)
	}
	res = netPay(t, ctx, svc, tenant, payrollengine.EmployeeInput{GrossPay: d("8000"), TaxCategory: "primary"})
	if !res.SHIFOrNHIF.Equal(d("250")) {
		t.Fatalf("SHIF after the platform change = %s, want 250", res.SHIFOrNHIF)
	}
	res = netPay(t, ctx, svc, other, payrollengine.EmployeeInput{GrossPay: d("8000"), TaxCategory: "primary"})
	if !res.SHIFOrNHIF.Equal(d("300")) {
		t.Fatalf("customised tenant SHIF = %s, want its own 300", res.SHIFOrNHIF)
	}
	// A tenant version from before minimums existed inherits the platform's; a recorded zero is
	// the tenant's own choice.
	client.PayrollFormula.UpdateOneID(own.ID).ClearMetadata().ExecX(ctx)
	res = netPay(t, ctx, svc, other, payrollengine.EmployeeInput{GrossPay: d("8000"), TaxCategory: "primary"})
	if !res.SHIFOrNHIF.Equal(d("250")) {
		t.Fatalf("legacy tenant version SHIF = %s, want the platform's 250", res.SHIFOrNHIF)
	}
	client.PayrollFormula.UpdateOneID(own.ID).SetMetadata(withMinimumContribution(nil, d("0"))).ExecX(ctx)
	res = netPay(t, ctx, svc, other, payrollengine.EmployeeInput{GrossPay: d("8000"), TaxCategory: "primary"})
	if !res.SHIFOrNHIF.Equal(d("220")) {
		t.Fatalf("tenant with a recorded zero SHIF = %s, want 220", res.SHIFOrNHIF)
	}
	// An update that leaves the minimum out keeps it.
	in.MinimumContribution = nil
	if _, err := svc.UpsertFormula(ctx, svc.SystemTenant(), in); err != nil {
		t.Fatal(err)
	}
	if m := FormulaMinimumContribution(client.PayrollFormula.GetX(ctx, platform.ID)); !m.Equal(d("250")) {
		t.Fatalf("minimum after an update without it = %s, want 250 kept", m)
	}
}

func decPtr(v decimal.Decimal) *decimal.Decimal { return &v }
