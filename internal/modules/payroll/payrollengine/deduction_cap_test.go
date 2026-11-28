package payrollengine

import (
	"testing"

	"github.com/shopspring/decimal"
)

// capConfig is the KRA config with the Employment Act s.19 limits: all deductions at most two
// thirds of wages (s.19(3)), and an employer loan at most half of what is left after the other
// deductions (s.19(1)(h)).
func capConfig() Config {
	cfg := kra2025Config()
	cfg.MaxDeductionShare = decimal.NewFromInt(2).DivRound(decimal.NewFromInt(3), 10)
	cfg.LoanShare = d("0.5")
	return cfg
}

// On 100,000 the statutory deductions and PAYE are 28,382.35 (net 71,617.65 before recoveries).

// A loan larger than net pay is cut to the s.19(1)(h) half of what is left after the other
// deductions; the rest is deferred and the employee keeps more than a third.
func TestDeductionCap_LoanLargerThanNetPay(t *testing.T) {
	res, err := Compute(capConfig(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		Loans: []Recoverable{{Installment: d("80000"), Outstanding: d("200000")}}})
	if err != nil {
		t.Fatal(err)
	}
	// Half of 100,000 - 28,382.35 is 35,808.825, taken as 35,808.82.
	if len(res.LoansApplied) != 1 || !res.LoansApplied[0].Equal(d("35808.82")) {
		t.Fatalf("loan applied = %v, want 35808.82", res.LoansApplied)
	}
	if !res.RecoveryDeferred.Equal(d("44191.18")) || !res.NetPay.Equal(d("35808.83")) {
		t.Errorf("deferred %s net %s, want 44191.18 / 35808.83", res.RecoveryDeferred, res.NetPay)
	}
	if !res.DeductionsAfterPAYE.Equal(d("35808.82")) {
		t.Errorf("after-PAYE = %s, want the capped loan", res.DeductionsAfterPAYE)
	}
	if !res.DeductionCap.Equal(d("66666.66")) || res.CapExceeded {
		t.Errorf("cap %s exceeded %v, want 66666.66 / false", res.DeductionCap, res.CapExceeded)
	}
}

// Without the Act's limits configured a loan still never takes net pay below zero.
func TestDeductionCap_NoLimitsNetNeverNegative(t *testing.T) {
	res, err := Compute(kra2025Config(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		Loans: []Recoverable{{Installment: d("80000"), Outstanding: d("100000")}}})
	if err != nil {
		t.Fatal(err)
	}
	if !res.LoansApplied[0].Equal(d("71617.65")) || !res.NetPay.IsZero() || !res.RecoveryDeferred.Equal(d("8382.35")) {
		t.Errorf("loan %s net %s deferred %s, want 71617.65 / 0 / 8382.35", res.LoansApplied[0], res.NetPay, res.RecoveryDeferred)
	}
	if !res.DeductionCap.IsZero() {
		t.Errorf("cap = %s, want none", res.DeductionCap)
	}
}

// Other deductions (SACCO) come before employer recoveries; the loan takes what the two-thirds
// limit leaves, which is less than its own half limit here.
func TestDeductionCap_OthersBeforeLoan(t *testing.T) {
	res, err := Compute(capConfig(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		Loans:           []Recoverable{{Installment: d("60000"), Outstanding: d("200000")}},
		OtherDeductions: []Deduction{{Phase: PhaseAfterPAYE, Priority: 6, Amount: d("10000")}}})
	if err != nil {
		t.Fatal(err)
	}
	// Room under two thirds: 66,666.66 - 28,382.35 - 10,000 = 28,284.31.
	if !res.OtherDeductionsApplied[0].Equal(d("10000")) || !res.LoansApplied[0].Equal(d("28284.31")) {
		t.Errorf("sacco %s loan %s, want 10000 / 28284.31", res.OtherDeductionsApplied[0], res.LoansApplied[0])
	}
	if !res.NetPay.Equal(d("33333.34")) || !res.RecoveryDeferred.Equal(d("31715.69")) || !res.DeductionShortfall.IsZero() {
		t.Errorf("net %s deferred %s short %s", res.NetPay, res.RecoveryDeferred, res.DeductionShortfall)
	}
}

// A deduction required by law (HELB) is taken in full like the statutory ones even past the cap;
// nothing else is then recovered and the payslip is flagged.
func TestDeductionCap_ByLawNeverCut(t *testing.T) {
	res, err := Compute(capConfig(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		Loans: []Recoverable{{Installment: d("5000"), Outstanding: d("50000")}},
		OtherDeductions: []Deduction{
			{Phase: PhaseAfterPAYE, Priority: 6, Amount: d("2000")},
			{Phase: PhaseAfterPAYE, Priority: 5, Amount: d("45000"), ByLaw: true},
		}})
	if err != nil {
		t.Fatal(err)
	}
	if !res.OtherDeductionsApplied[1].Equal(d("45000")) || !res.OtherDeductionsApplied[0].IsZero() || !res.LoansApplied[0].IsZero() {
		t.Errorf("helb %s sacco %s loan %s, want 45000 / 0 / 0", res.OtherDeductionsApplied[1], res.OtherDeductionsApplied[0], res.LoansApplied[0])
	}
	if !res.CapExceeded || !res.DeductionShortfall.Equal(d("2000")) || !res.RecoveryDeferred.Equal(d("5000")) {
		t.Errorf("exceeded %v short %s deferred %s", res.CapExceeded, res.DeductionShortfall, res.RecoveryDeferred)
	}
	if !res.NetPay.Equal(d("26617.65")) {
		t.Errorf("net = %s, want 26617.65", res.NetPay)
	}
	// Even a by-law deduction cannot take more cash than is left.
	res, _ = Compute(capConfig(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		OtherDeductions: []Deduction{{Phase: PhaseAfterPAYE, Amount: d("90000"), ByLaw: true}}})
	if !res.OtherDeductionsApplied[0].Equal(d("71617.65")) || !res.NetPay.IsZero() || !res.DeductionShortfall.Equal(d("18382.35")) {
		t.Errorf("helb beyond net: applied %s net %s short %s", res.OtherDeductionsApplied[0], res.NetPay, res.DeductionShortfall)
	}
}

// Recoveries are cut in the order loans, advances, staff purchases, losses: the advance is taken
// before the loan, and the loan's half limit counts the advance as another deduction.
func TestDeductionCap_AdvanceBeforeLoan(t *testing.T) {
	cfg := capConfig()
	cfg.RecoverAdvances = true
	res, err := Compute(cfg, EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		Loans:    []Recoverable{{Installment: d("30000"), Outstanding: d("90000")}},
		Advances: []Recoverable{{Installment: d("20000"), Outstanding: d("20000")}}})
	if err != nil {
		t.Fatal(err)
	}
	// Room 38,284.31: advance 20,000, loan min(30,000, 18,284.31, half of 51,617.65).
	if !res.AdvancesApplied[0].Equal(d("20000")) || !res.LoansApplied[0].Equal(d("18284.31")) {
		t.Errorf("advance %s loan %s, want 20000 / 18284.31", res.AdvancesApplied[0], res.LoansApplied[0])
	}
	if !res.RecoveryDeferred.Equal(d("11715.69")) || !res.NetPay.Equal(d("33333.34")) {
		t.Errorf("deferred %s net %s", res.RecoveryDeferred, res.NetPay)
	}
}

// Within the limits nothing changes: every installment is taken in full.
func TestDeductionCap_WithinLimitsUnchanged(t *testing.T) {
	res, err := Compute(capConfig(), EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		Loans:          []Recoverable{{Installment: d("5000"), Outstanding: d("1200")}},
		StaffPurchases: []Recoverable{{Installment: d("3000"), Outstanding: d("9000")}},
		LossDamages:    []Recoverable{{Installment: d("1000"), Outstanding: d("1000")}}})
	if err != nil {
		t.Fatal(err)
	}
	if !res.DeductionsAfterPAYE.Equal(d("5200")) || !res.RecoveryDeferred.IsZero() || !res.NetPay.Equal(d("66417.65")) {
		t.Errorf("after-PAYE %s deferred %s net %s", res.DeductionsAfterPAYE, res.RecoveryDeferred, res.NetPay)
	}
	if !res.LoansApplied[0].Equal(d("1200")) || !res.StaffPurchasesApplied[0].Equal(d("3000")) || !res.LossDamagesApplied[0].Equal(d("1000")) {
		t.Errorf("applied loan %v staff %v loss %v", res.LoansApplied, res.StaffPurchasesApplied, res.LossDamagesApplied)
	}
}
