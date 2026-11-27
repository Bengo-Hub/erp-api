package payrollengine

import "testing"

// An earning can count for PAYE but not for NSSF, SHIF or the Housing Levy: each levy is charged
// on its own base (gross plus that levy's adjustment), PAYE on gross with its own adjustment.
func TestLevyBases(t *testing.T) {
	cfg := KRADefaults()
	cfg.NSSF = NSSFYear4()
	in := EmployeeInput{GrossPay: d("50000"), TaxableAllowances: d("10000"), TaxCategory: "primary",
		LevyAdjust: LevyAdjust{NSSF: d("-10000"), SHIF: d("-10000"), HousingLevy: d("-10000")}}
	res, err := Compute(cfg, in)
	if err != nil {
		t.Fatal(err)
	}
	// The run records the base each levy was charged on, for the returns.
	if !res.NSSFBase.Equal(d("50000")) || !res.SHIFBase.Equal(d("50000")) || !res.HousingLevyBase.Equal(d("50000")) {
		t.Errorf("bases nssf %s shif %s ahl %s, want 50000 each", res.NSSFBase, res.SHIFBase, res.HousingLevyBase)
	}
	nssf := res.NSSFEmployeeTier1.Add(res.NSSFEmployeeTier2)
	if !nssf.Equal(d("3000")) || !res.SHIFOrNHIF.Equal(d("1375")) || !res.HousingLevy.Equal(d("750")) {
		t.Errorf("levies on 50,000: nssf %s shif %s ahl %s", nssf, res.SHIFOrNHIF, res.HousingLevy)
	}
	// PAYE still on the whole 60,000 less the deductible levies.
	if !res.GrossPay.Equal(d("60000")) || !res.TaxablePay.Equal(d("54875")) {
		t.Errorf("gross %s taxable %s, want 60000 and 54875", res.GrossPay, res.TaxablePay)
	}

	// A non-taxable earning counted for SHIF only.
	in2 := EmployeeInput{GrossPay: d("50000"), TaxCategory: "primary", NonTaxableEarnings: d("4000"),
		LevyAdjust: LevyAdjust{SHIF: d("4000")}}
	res2, _ := Compute(cfg, in2)
	if !res2.SHIFOrNHIF.Equal(d("1485")) || !res2.HousingLevy.Equal(d("750")) {
		t.Errorf("shif %s ahl %s, want 1485 and 750", res2.SHIFOrNHIF, res2.HousingLevy)
	}

	// PAYE adjustment: an amount in gross that PAYE leaves out.
	in3 := EmployeeInput{GrossPay: d("50000"), TaxableAllowances: d("5000"), TaxCategory: "primary", LevyAdjust: LevyAdjust{PAYE: d("-5000")}}
	res3, _ := Compute(cfg, in3)
	base, _ := Compute(cfg, EmployeeInput{GrossPay: d("55000"), TaxCategory: "primary"})
	if !res3.TaxablePay.Equal(base.TaxablePay.Sub(d("5000"))) {
		t.Errorf("taxable %s, want %s", res3.TaxablePay, base.TaxablePay.Sub(d("5000")))
	}
}

// Income Tax Act s.22A(1)(b): the pension deduction is capped at 30% of pensionable pay, not of
// gross. Without a pensionable figure the engine keeps using gross.
func TestPensionCapOnPensionablePay(t *testing.T) {
	cfg := KRADefaults()
	cfg.PensionReliefCap = d("30000")
	in := EmployeeInput{GrossPay: d("50000"), TaxableAllowances: d("10000"), TaxCategory: "primary",
		PensionContribution: d("20000"), PensionablePay: d("50000")}
	res, _ := Compute(cfg, in)
	if !res.PensionDeduction.Equal(d("15000")) {
		t.Errorf("pension deduction %s, want 15000 (30%% of 50,000 pensionable)", res.PensionDeduction)
	}
	in.PensionablePay = d("0")
	res, _ = Compute(cfg, in)
	if !res.PensionDeduction.Equal(d("18000")) {
		t.Errorf("without pensionable pay: %s, want 18000 (30%% of gross)", res.PensionDeduction)
	}
}
