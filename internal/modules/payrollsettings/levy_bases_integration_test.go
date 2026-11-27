package payrollsettings

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
)

// Rules are stored per tenant and month, a past month is refused, the tenant's rule wins over the
// platform's, and an earning without any rule keeps the old treatment.
func TestIntegration_LevyBases(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	sys, tenant := uuid.New(), uuid.New()
	svc := NewService(client, sys)
	next := time.Now().UTC().AddDate(0, 1, 0)
	from := next.Format("2006-01")

	if _, err := svc.SetLevyRule(ctx, sys, "bonus", LevyRule{From: "2020-01", Flags: LevyFlags{PAYE: true}}); err == nil {
		t.Error("a rule for a month already paid must be refused")
	}
	if _, err := svc.SetLevyRule(ctx, sys, "bonus", LevyRule{From: from, Flags: LevyFlags{PAYE: true}}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.SetLevyRule(ctx, tenant, "bonus", LevyRule{From: from, Flags: LevyFlags{PAYE: true, SHIF: true}}); err != nil {
		t.Fatal(err)
	}
	r, err := svc.LevyResolver(ctx, tenant, time.Date(next.Year(), next.Month(), 1, 0, 0, 0, 0, time.UTC))
	if err != nil {
		t.Fatal(err)
	}
	if f := r.Flags("bonus", "taxable"); !f.PAYE || !f.SHIF || f.NSSF || f.HousingLevy {
		t.Errorf("tenant rule not applied: %+v", f)
	}
	other, _ := svc.LevyResolver(ctx, uuid.New(), time.Date(next.Year(), next.Month(), 1, 0, 0, 0, 0, time.UTC))
	if f := other.Flags("bonus", "taxable"); !f.PAYE || f.SHIF || f.NSSF {
		t.Errorf("platform rule not inherited: %+v", f)
	}
	now, _ := svc.LevyResolver(ctx, tenant, time.Now().UTC())
	if f := now.Flags("bonus", "taxable"); !(f.PAYE && f.NSSF && f.SHIF && f.HousingLevy) || f.Pensionable {
		t.Errorf("this month must keep the old treatment: %+v", f)
	}
	if f := now.Flags("basic", "taxable"); !f.Pensionable {
		t.Error("basic pay is pensionable by default")
	}

	// A future rule can be cancelled; a rule already in force cannot.
	cur := time.Now().UTC().Format("2006-01")
	if _, err := svc.SetLevyRule(ctx, tenant, "house_allowance", LevyRule{From: cur, Flags: LevyFlags{PAYE: true}}); err != nil {
		t.Fatal(err)
	}
	if _, err := svc.CancelLevyRule(ctx, tenant, "house_allowance", cur); err == nil {
		t.Error("a rule in force this month must not be cancellable")
	}
	bases, err := svc.CancelLevyRule(ctx, tenant, "bonus", from)
	if err != nil {
		t.Fatalf("cancel future rule: %v", err)
	}
	if len(bases["bonus"]) != 0 {
		t.Errorf("bonus rules after cancel = %v", bases["bonus"])
	}
	if _, err := svc.CancelLevyRule(ctx, tenant, "bonus", from); err == nil {
		t.Error("cancelling a rule that is not there must say so")
	}
}
