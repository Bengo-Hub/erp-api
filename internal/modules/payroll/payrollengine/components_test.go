package payrollengine

import "testing"

// SHIF is 2.75% of gross with a KES 300 monthly minimum carried on the formula, not hard-coded.
func TestSHIFMinimumContribution(t *testing.T) {
	cfg := kra2025Config()
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("8000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatal(err)
	}
	if !res.SHIFOrNHIF.Equal(d("300")) { // 2.75% of 8,000 is 220
		t.Errorf("SHIF on 8,000 = %s, want the 300 minimum", res.SHIFOrNHIF)
	}
	// Above the floor the percentage applies.
	res, _ = Compute(cfg, EmployeeInput{GrossPay: d("20000"), TaxCategory: "primary"})
	if !res.SHIFOrNHIF.Equal(d("550")) {
		t.Errorf("SHIF on 20,000 = %s, want 550", res.SHIFOrNHIF)
	}
	// No pay, no contribution.
	res, _ = Compute(cfg, EmployeeInput{GrossPay: d("0"), TaxCategory: "primary"})
	if !res.SHIFOrNHIF.IsZero() {
		t.Errorf("SHIF on 0 = %s, want 0", res.SHIFOrNHIF)
	}
	// A formula without a minimum charges the plain percentage.
	shif := *cfg.SHIF
	shif.MinimumContribution = d("0")
	cfg.SHIF = &shif
	res, _ = Compute(cfg, EmployeeInput{GrossPay: d("8000"), TaxCategory: "primary"})
	if !res.SHIFOrNHIF.Equal(d("220")) {
		t.Errorf("SHIF without a minimum = %s, want 220", res.SHIFOrNHIF)
	}
}

// PAYE band 4 runs to 800,000: the next 300,000 above 500,000 is taxed at 32.5%, the rest at 35%.
func TestPAYEBand4Limit(t *testing.T) {
	for income, want := range map[string]string{"800000": "242283.35", "800001": "242283.70", "900000": "277283.35"} {
		tax, err := CalculateIncomeTax(kra2025Config().Income, d(income))
		if err != nil || !tax.Equal(d(want)) {
			t.Errorf("tax on %s = %s (%v), want %s", income, tax, err, want)
		}
	}
}

// A taxable earning is taxed like basic pay; a non-taxable one adds to gross and net only.
func TestComponentEarnings_TaxableVsNonTaxable(t *testing.T) {
	cfg := kra2025Config()
	taxable, err := Compute(cfg, EmployeeInput{GrossPay: d("90000"), TaxableAllowances: d("10000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatal(err)
	}
	// 90,000 basic + 10,000 taxable allowance is the golden master.
	if !taxable.NetPay.Equal(d("71617.65")) || !taxable.GrossPay.Equal(d("100000")) {
		t.Errorf("taxable earning: gross %s net %s, want 100000 / 71617.65", taxable.GrossPay, taxable.NetPay)
	}
	free, err := Compute(cfg, EmployeeInput{GrossPay: d("90000"), NonTaxableEarnings: d("10000"), TaxCategory: "primary"})
	if err != nil {
		t.Fatal(err)
	}
	base, _ := Compute(cfg, EmployeeInput{GrossPay: d("90000"), TaxCategory: "primary"})
	if !free.GrossPay.Equal(d("100000")) || !free.NonTaxableEarnings.Equal(d("10000")) {
		t.Errorf("non-taxable earning: gross %s, want 100000 with 10000 non-taxable", free.GrossPay)
	}
	if !free.PAYE.Equal(base.PAYE) || !free.TaxablePay.Equal(base.TaxablePay) || !free.SHIFOrNHIF.Equal(base.SHIFOrNHIF) {
		t.Errorf("non-taxable earning changed PAYE/taxable/SHIF: %s/%s/%s vs %s/%s/%s",
			free.PAYE, free.TaxablePay, free.SHIFOrNHIF, base.PAYE, base.TaxablePay, base.SHIFOrNHIF)
	}
	if !free.NetPay.Equal(base.NetPay.Add(d("10000"))) {
		t.Errorf("non-taxable earning net %s, want %s", free.NetPay, base.NetPay.Add(d("10000")))
	}
}

// Opt-in deductions come off after the statutory deductions in phase and priority order; the
// golden master is unchanged by an empty list.
func TestOtherDeductions_AfterStatutory(t *testing.T) {
	cfg := kra2025Config()
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		OtherDeductions: []Deduction{{Phase: PhaseAfterPAYE, Priority: 6, Amount: d("2000")}, {Phase: PhaseAfterPAYE, Priority: 5, Amount: d("1500")}}})
	if err != nil {
		t.Fatal(err)
	}
	if !res.NetPay.Equal(d("68117.65")) || !res.OtherDeductions.Equal(d("3500")) || !res.DeductionShortfall.IsZero() {
		t.Errorf("net %s other %s short %s, want 68117.65 / 3500 / 0", res.NetPay, res.OtherDeductions, res.DeductionShortfall)
	}
	if !res.PAYE.Equal(d("19812.35")) || !res.DeductionsAfterPAYE.Equal(d("3500")) {
		t.Errorf("PAYE %s after-PAYE %s: an after-PAYE deduction must not change tax", res.PAYE, res.DeductionsAfterPAYE)
	}
}

// The opt-in deductions come before the loan; the loan takes the net pay left and the rest of
// its installment is deferred, so net pay never goes below zero.
func TestOtherDeductions_CappedAtNet(t *testing.T) {
	cfg := kra2025Config()
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		Loans: []Recoverable{{Installment: d("60000"), Outstanding: d("100000")}},
		OtherDeductions: []Deduction{
			{Phase: PhaseAfterPAYE, Priority: 6, Amount: d("10000")}, // SACCO, second
			{Phase: PhaseAfterPAYE, Priority: 5, Amount: d("5000")},  // HELB, first
		}})
	if err != nil {
		t.Fatal(err)
	}
	// After statutory and PAYE 71,617.65 is left: HELB 5,000 and SACCO 10,000 in full, then the
	// loan 56,617.65 of 60,000.
	if !res.OtherDeductionsApplied[1].Equal(d("5000")) || !res.OtherDeductionsApplied[0].Equal(d("10000")) {
		t.Errorf("applied = %v, want [10000 5000]", res.OtherDeductionsApplied)
	}
	if !res.LoansApplied[0].Equal(d("56617.65")) || !res.RecoveryDeferred.Equal(d("3382.35")) || !res.NetPay.IsZero() {
		t.Errorf("loan %s deferred %s net %s, want 56617.65 / 3382.35 / 0", res.LoansApplied[0], res.RecoveryDeferred, res.NetPay)
	}
	if !res.DeductionShortfall.IsZero() || !res.DeductionsAfterPAYE.Equal(d("71617.65")) {
		t.Errorf("shortfall %s after-PAYE %s, want 0 / 71617.65", res.DeductionShortfall, res.DeductionsAfterPAYE)
	}
	// A loan beyond net pay: the opt-in deduction is taken, the loan takes the rest.
	res, _ = Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		Loans:           []Recoverable{{Installment: d("80000"), Outstanding: d("100000")}},
		OtherDeductions: []Deduction{{Phase: PhaseAfterPAYE, Amount: d("1000")}}})
	if !res.OtherDeductions.Equal(d("1000")) || !res.LoansApplied[0].Equal(d("70617.65")) || !res.NetPay.IsZero() {
		t.Errorf("loan beyond net: other %s loan %s net %s", res.OtherDeductions, res.LoansApplied[0], res.NetPay)
	}
}
