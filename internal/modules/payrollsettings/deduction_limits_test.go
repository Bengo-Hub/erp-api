package payrollsettings

import (
	"context"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

func TestParseShare(t *testing.T) {
	for in, want := range map[string]string{"2/3": "0.6666666667", "0.5": "0.5", "1/2": "0.5", "1": "1", " 3/4 ": "0.75"} {
		got, err := ParseShare(in)
		if err != nil || !got.Equal(decimal.RequireFromString(want)) {
			t.Errorf("ParseShare(%q) = %s, %v; want %s", in, got, err, want)
		}
	}
	for _, bad := range []string{"", "0", "-1", "1.5", "3/2", "a/b", "1/0", "2/"} {
		if _, err := ParseShare(bad); err == nil {
			t.Errorf("ParseShare(%q) must fail", bad)
		}
	}
}

// Without any setting the Employment Act limits apply and HELB and court orders are by law; a
// platform value overrides the Act's default and a tenant value overrides the platform's.
func TestResolveDeductionLimits(t *testing.T) {
	l := ResolveDeductionLimits(DeductionLimitsDoc{}, DeductionLimitsDoc{})
	if l.MaxShare.String() != "0.6666666667" || l.LoanShare.String() != "0.5" {
		t.Errorf("defaults = %s / %s, want two thirds / half", l.MaxShare, l.LoanShare)
	}
	if !l.IsByLaw("helb", uuid.Nil) || !l.IsByLaw("court_order", uuid.Nil) || l.IsByLaw("sacco", uuid.Nil) {
		t.Errorf("default by-law list = %v", l.ByLaw)
	}
	half := "1/2"
	platform := DeductionLimitsDoc{MaxShare: &half}
	own := uuid.New()
	tenantList := []string{"helb", own.String()}
	tenant := DeductionLimitsDoc{ByLaw: &tenantList}
	l = ResolveDeductionLimits(tenant, platform)
	if l.MaxShare.String() != "0.5" || l.IsByLaw("court_order", uuid.Nil) || !l.IsByLaw("", own) {
		t.Errorf("resolved = %+v", l)
	}
	empty := []string{}
	l = ResolveDeductionLimits(DeductionLimitsDoc{ByLaw: &empty}, platform)
	if l.IsByLaw("helb", uuid.Nil) {
		t.Error("an empty tenant list must replace the default")
	}
}

func TestIntegration_DeductionLimits(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	sys, tenant := uuid.New(), uuid.New()
	svc := NewService(client, sys)

	l, err := svc.DeductionLimitsFor(ctx, tenant)
	if err != nil || l.MaxShare.String() != "0.6666666667" {
		t.Fatalf("defaults: %+v %v", l, err)
	}
	if _, err := svc.SetDeductionLimits(ctx, tenant, DeductionLimitsDoc{MaxShare: strp("1.5")}); err == nil {
		t.Error("a share above 1 must be refused")
	}
	if _, err := svc.SetDeductionLimits(ctx, sys, DeductionLimitsDoc{LoanShare: strp("2/5")}); err != nil {
		t.Fatal(err)
	}
	list := []string{"sacco"}
	if _, err := svc.SetDeductionLimits(ctx, tenant, DeductionLimitsDoc{MaxShare: strp("3/4"), ByLaw: &list}); err != nil {
		t.Fatal(err)
	}
	l, _ = svc.DeductionLimitsFor(ctx, tenant)
	if l.MaxShare.String() != "0.75" || l.LoanShare.String() != "0.4" || !l.IsByLaw("sacco", uuid.Nil) || l.IsByLaw("helb", uuid.Nil) {
		t.Errorf("tenant limits = %+v", l)
	}
	other, _ := svc.DeductionLimitsFor(ctx, uuid.New())
	if other.MaxShare.String() != "0.6666666667" || other.LoanShare.String() != "0.4" || !other.IsByLaw("helb", uuid.Nil) {
		t.Errorf("another tenant = %+v", other)
	}
	// Clearing the tenant's own values inherits again.
	if _, err := svc.SetDeductionLimits(ctx, tenant, DeductionLimitsDoc{}); err != nil {
		t.Fatal(err)
	}
	l, _ = svc.DeductionLimitsFor(ctx, tenant)
	if l.MaxShare.String() != "0.6666666667" || !l.IsByLaw("helb", uuid.Nil) {
		t.Errorf("after reset = %+v", l)
	}
}

func strp(s string) *string { return &s }
