package payrollengine

import "testing"

// Income Tax Act s.12B: the employer pays fringe benefit tax on the gap between interest at the
// market rate and the interest the employee actually pays, never below zero. It never touches
// the employee's pay.
func TestFringeBenefitTax(t *testing.T) {
	cfg := KRADefaults()
	cfg.FBT = &FBTRates{TaxRate: d("0.30"), MarketRate: d("9")}
	in := EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary", StaffLoans: []LoanBenefit{
		{Outstanding: d("120000"), AnnualRate: d("3")}, // 6% gap: 600 a month, FBT 180
		{Outstanding: d("50000"), AnnualRate: d("12")}, // above market: nothing
	}}
	res, err := Compute(cfg, in)
	if err != nil {
		t.Fatal(err)
	}
	if !res.FBTEmployer.Equal(d("180")) {
		t.Errorf("FBT %s, want 180", res.FBTEmployer)
	}
	plain, _ := Compute(KRADefaults(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	if !res.NetPay.Equal(plain.NetPay) || !res.PAYE.Equal(plain.PAYE) {
		t.Errorf("FBT changed the employee's pay: net %s vs %s", res.NetPay, plain.NetPay)
	}
	cfg.FBT = nil
	none, _ := Compute(cfg, in)
	if !none.FBTEmployer.IsZero() {
		t.Errorf("no FBT rule, FBT %s", none.FBTEmployer)
	}
}

// TaxableOnly (the per diem above the daily tax-free limit) is taxed but is not cash pay and not
// a statutory base: the claim is already paid in full as a reimbursement.
func TestTaxableOnlyAddsToPAYEOnly(t *testing.T) {
	base, _ := Compute(KRADefaults(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary"})
	res, err := Compute(KRADefaults(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary", TaxableOnly: d("2000")})
	if err != nil {
		t.Fatal(err)
	}
	if !res.TaxablePay.Sub(base.TaxablePay).Equal(d("2000")) || !base.PAYE.Sub(res.PAYE).Neg().Equal(d("600")) {
		t.Errorf("taxable +%s PAYE +%s, want 2000 and 600", res.TaxablePay.Sub(base.TaxablePay), res.PAYE.Sub(base.PAYE))
	}
	if !res.SHIFOrNHIF.Equal(base.SHIFOrNHIF) || !res.GrossPay.Equal(base.GrossPay) {
		t.Error("taxable-only amount changed gross or a statutory base")
	}
}
