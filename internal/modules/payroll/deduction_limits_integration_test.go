package payroll

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/recoveryline"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// A staff loan larger than net pay is cut to the Employment Act s.19 limits: the recovery line
// frozen for disburse holds the amount taken, the payslip and the run status show the deferred
// rest, and a HELB deduction (required by law) is taken in full first.
func TestIntegration_DeductionLimitsInRun(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	d := decimal.RequireFromString
	set := payrollsettings.NewService(client, uuid.New())
	seedPlatformPayroll(t, ctx, client, set)
	svc := NewService(client, set)
	tenant := uuid.New()
	sep := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)

	comps, err := set.ResolveComponents(ctx, tenant, "")
	if err != nil {
		t.Fatal(err)
	}
	var helb uuid.UUID
	for _, c := range comps {
		if c.Code == "helb" {
			helb = c.Component.ID
		}
	}
	if _, err := set.SetComponentActive(ctx, tenant, helb, true); err != nil {
		t.Fatal(err)
	}

	e := client.Employee.Create().SetTenantID(tenant).SetFirstName("Wanjiru").SaveX(ctx)
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(e.ID).SetMonthlySalary(d("100000")).SaveX(ctx)
	loan := client.EmployeeLoan.Create().SetTenantID(tenant).SetEmployeeID(e.ID).SetIsActive(true).
		SetPrincipalAmount(d("200000")).SetMonthlyInstallment(d("80000")).SaveX(ctx)
	ref := "HELB-1"
	amt := d("5000")
	if _, err := set.SaveAssignment(ctx, tenant, e.ID, nil, payrollsettings.AssignmentInput{ComponentID: helb, Amount: &amt, Reference: ref}); err != nil {
		t.Fatal(err)
	}

	out, err := svc.Run(ctx, RunParams{TenantID: tenant, Period: sep, Persist: true})
	if err != nil || len(out) != 1 {
		t.Fatalf("run = %v %v", out, err)
	}
	res := out[0].Result
	// 100,000 gross: statutory and PAYE 28,382.35, HELB 5,000 in full. The loan may take half of
	// the 66,617.65 left (33,308.82), and two thirds of wages (66,666.66) leaves 33,284.31: the
	// smaller wins.
	if !res.OtherDeductions.Equal(d("5000")) || !res.LoansApplied[0].Equal(d("33284.31")) {
		t.Fatalf("helb %s loan %v, want 5000 / 33284.31", res.OtherDeductions, res.LoansApplied)
	}
	if !res.RecoveryDeferred.Equal(d("46715.69")) || !res.NetPay.Equal(d("33333.34")) {
		t.Errorf("deferred %s net %s, want 46715.69 / 33333.34", res.RecoveryDeferred, res.NetPay)
	}

	rl := client.RecoveryLine.Query().Where(recoveryline.TenantID(tenant), recoveryline.RecoverableID(loan.ID)).OnlyX(ctx)
	if !rl.Amount.Equal(d("33284.31")) {
		t.Errorf("frozen loan recovery = %s, want the 33284.31 taken", rl.Amount)
	}
	lines := payslipLines(t, ctx, client, tenant, e.ID, sep)
	if l := lines["Loan"]; l == nil || !l.CashAmount.Equal(d("33284.31")) {
		t.Errorf("loan line = %v, want 33284.31", l)
	}
	if l := lines["Loan (deferred to next month)"]; l == nil || !l.CashAmount.Equal(d("46715.69")) || l.Section != secShortfall {
		t.Errorf("deferred line = %v, want 46715.69 informational", l)
	}

	st, err := svc.GetRunStatus(ctx, tenant, sep, uuid.Nil)
	if err != nil {
		t.Fatal(err)
	}
	if st.DeferredTotal != "46715.69" || len(st.Shortfalls) != 1 || st.Shortfalls[0].Kind != "deferred" ||
		st.Shortfalls[0].EmployeeName != "Wanjiru" {
		t.Errorf("run status shortfalls = %+v total %s", st.Shortfalls, st.DeferredTotal)
	}

	// A tenant that drops HELB from its by-law list and lowers the limit to a half: HELB is now an
	// ordinary deduction within the limit.
	empty := []string{}
	half := "1/2"
	if _, err := set.SetDeductionLimits(ctx, tenant, payrollsettings.DeductionLimitsDoc{MaxShare: &half, ByLaw: &empty}); err != nil {
		t.Fatal(err)
	}
	out, err = svc.Run(ctx, RunParams{TenantID: tenant, Period: sep})
	if err != nil {
		t.Fatal(err)
	}
	// Half of 100,000 less 28,382.35 leaves 21,617.65: HELB 5,000, loan 16,617.65.
	if r := out[0].Result; !r.LoansApplied[0].Equal(d("16617.65")) || !r.NetPay.Equal(d("50000")) {
		t.Errorf("half limit: loan %v net %s, want 16617.65 / 50000", r.LoansApplied, r.NetPay)
	}
}
