package payroll

import (
	"testing"
	"time"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// The pension limit moves to pensionable pay from December 2026. With basic 50,000, a 10,000
// house allowance (not pensionable by default) and a 20,000 pension contribution:
//   - November: 30% of gross 60,000 = 18,000 deductible;
//   - December: 30% of pensionable 50,000 = 15,000 deductible, so taxable pay rises by 3,000 and
//     PAYE by 900 (30% band).
func TestPensionReliefOnPensionablePayFromDecember(t *testing.T) {
	dec := decimal.RequireFromString
	cfg := payrollengine.KRADefaults()
	cfg.NSSF = payrollengine.NSSFYear4()
	cfg.PensionReliefCap = dec("30000")
	run := func(period time.Time) payrollengine.PayslipResult {
		r := payrollsettings.NewLevyResolver(period, nil, nil)
		in := payrollengine.EmployeeInput{GrossPay: dec("50000"), TaxableAllowances: dec("10000"), TaxCategory: "primary", PensionContribution: dec("20000")}
		countEarning(&in, r.Flags("basic", "taxable"), dec("50000"), true, true)
		countEarning(&in, r.Flags("house_allowance", "taxable"), dec("10000"), true, true)
		in.PensionablePay = pensionableFor(period, in.PensionablePay)
		res, err := payrollengine.Compute(cfg, in)
		if err != nil {
			t.Fatal(err)
		}
		return res
	}
	nov := run(time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC))
	decr := run(time.Date(2026, 12, 1, 0, 0, 0, 0, time.UTC))
	if !nov.PensionDeduction.Equal(dec("18000")) || !decr.PensionDeduction.Equal(dec("15000")) {
		t.Fatalf("pension deduction nov %s dec %s, want 18000 and 15000", nov.PensionDeduction, decr.PensionDeduction)
	}
	if !decr.TaxablePay.Sub(nov.TaxablePay).Equal(dec("3000")) || !decr.PAYE.Sub(nov.PAYE).Equal(dec("900")) {
		t.Errorf("taxable +%s PAYE +%s, want 3000 and 900", decr.TaxablePay.Sub(nov.TaxablePay), decr.PAYE.Sub(nov.PAYE))
	}
}

// Without rules every earning keeps its old treatment, so the worked examples do not move; a dated
// rule changes an earning's levies from its month only, and a tenant rule wins over the platform's.
func TestLevyFlagsFromRules(t *testing.T) {
	dec := decimal.RequireFromString
	nov, dec26 := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC), time.Date(2026, 12, 1, 0, 0, 0, 0, time.UTC)
	platform := payrollsettings.LevyBases{"transport_allowance": {{From: "2026-12", Flags: payrollsettings.LevyFlags{PAYE: true}}}}
	tenant := payrollsettings.LevyBases{"house_allowance": {{From: "2026-01", Flags: payrollsettings.LevyFlags{PAYE: true, Pensionable: true}}}}

	build := func(period time.Time) payrollengine.EmployeeInput {
		r := payrollsettings.NewLevyResolver(period, tenant, platform)
		in := payrollengine.EmployeeInput{GrossPay: dec("50000"), TaxableAllowances: dec("15000"), TaxCategory: "primary"}
		countEarning(&in, r.Flags("basic", "taxable"), dec("50000"), true, true)
		countEarning(&in, r.Flags("transport_allowance", "taxable"), dec("5000"), true, true)
		countEarning(&in, r.Flags("house_allowance", "taxable"), dec("10000"), true, true)
		countEarning(&in, r.Flags("meal_allowance", "nontaxable"), dec("2000"), false, false)
		return in
	}
	in := build(nov)
	// November: transport still counts everywhere; the tenant's house allowance rule (from Jan)
	// takes it out of the three levies and makes it pensionable.
	if !in.LevyAdjust.NSSF.Equal(dec("-10000")) || !in.LevyAdjust.PAYE.IsZero() || !in.PensionablePay.Equal(dec("60000")) {
		t.Errorf("november: adjust %+v pensionable %s", in.LevyAdjust, in.PensionablePay)
	}
	in = build(dec26)
	if !in.LevyAdjust.NSSF.Equal(dec("-15000")) || !in.LevyAdjust.SHIF.Equal(dec("-15000")) || !in.LevyAdjust.HousingLevy.Equal(dec("-15000")) {
		t.Errorf("december: adjust %+v", in.LevyAdjust)
	}

	// No rules at all: nothing moves.
	r := payrollsettings.NewLevyResolver(nov, nil, nil)
	plain := payrollengine.EmployeeInput{GrossPay: dec("50000")}
	countEarning(&plain, r.Flags("basic", "taxable"), dec("50000"), true, true)
	countEarning(&plain, r.Flags("bonus", "taxable"), dec("10000"), true, true)
	countEarning(&plain, r.Flags("per_diem", "nontaxable"), dec("3000"), false, false)
	if a := plain.LevyAdjust; !(a.PAYE.IsZero() && a.NSSF.IsZero() && a.SHIF.IsZero() && a.HousingLevy.IsZero()) {
		t.Errorf("defaults moved a base: %+v", plain.LevyAdjust)
	}
	if !plain.PensionablePay.Equal(dec("50000")) {
		t.Errorf("pensionable %s, want basic only", plain.PensionablePay)
	}
}
