package payroll

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

func TestWHTRatesValidateAndFraction(t *testing.T) {
	d := decimal.RequireFromString
	def := DefaultWHTRates()
	if !def.fraction(true).Equal(d("0.05")) || !def.fraction(false).Equal(d("0.2")) {
		t.Fatalf("defaults = %s / %s, want 5%% resident and 20%% non-resident", def.fraction(true), def.fraction(false))
	}
	for _, bad := range []WHTRates{{Resident: d("-1"), NonResident: d("20")}, {Resident: d("5"), NonResident: d("101")}} {
		if bad.Validate() == nil {
			t.Errorf("%+v should be rejected", bad)
		}
	}
	if (WHTRates{Resident: d("3"), NonResident: d("15")}).Validate() != nil {
		t.Error("valid rates rejected")
	}
}

// Tenant rates apply per residency: a resident voucher never takes the non-resident rate.
func TestIntegration_ConsultantVoucherUsesResidencyRate(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	d := decimal.RequireFromString
	svc := NewService(client, nil)
	emp := client.Employee.Create().SetTenantID(tenant).SetFirstName("C").SaveX(ctx)

	if r, _ := svc.GetWHTRates(ctx, tenant); !r.Resident.Equal(d("5")) || !r.NonResident.Equal(d("20")) {
		t.Fatalf("unset rates = %+v, want the defaults", r)
	}
	if _, err := svc.SaveWHTRates(ctx, tenant, WHTRates{Resident: d("3"), NonResident: d("15")}); err != nil {
		t.Fatal(err)
	}
	res, err := svc.CreateConsultantVoucher(ctx, tenant, ConsultantVoucherInput{EmployeeID: emp.ID, GrossAmount: d("10000"), IsResident: true})
	if err != nil {
		t.Fatal(err)
	}
	non, err := svc.CreateConsultantVoucher(ctx, tenant, ConsultantVoucherInput{EmployeeID: emp.ID, GrossAmount: d("10000"), IsResident: false})
	if err != nil {
		t.Fatal(err)
	}
	if !res.WhtAmount.Equal(d("300")) || !non.WhtAmount.Equal(d("1500")) {
		t.Fatalf("wht = %s resident / %s non-resident, want 300 / 1500", res.WhtAmount, non.WhtAmount)
	}
	// Another tenant keeps the defaults.
	if r, _ := svc.GetWHTRates(ctx, uuid.New()); !r.Resident.Equal(d("5")) {
		t.Fatalf("rates leaked across tenants: %+v", r)
	}
}
