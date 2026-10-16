package payroll

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/staffpurchasededuction"
)

// The batched run inputs must give the engine exactly what the per-employee reads used to.
func TestIntegration_RunInputsBatch(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	tenant := uuid.New()
	d := decimal.RequireFromString
	sep := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)
	before, after := sep.AddDate(0, -2, 0), sep.AddDate(0, 2, 0)

	a := client.Employee.Create().SetTenantID(tenant).SetFirstName("A").SaveX(ctx)
	b := client.Employee.Create().SetTenantID(tenant).SetFirstName("B").SaveX(ctx)
	noSalary := client.Employee.Create().SetTenantID(tenant).SetFirstName("C").SaveX(ctx)

	// Two active salaries for A: the newest wins.
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetMonthlySalary(d("50000")).
		SetCreatedAt(sep.AddDate(-1, 0, 0)).SaveX(ctx)
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetMonthlySalary(d("60000")).
		SetIncomeTax("secondary").SetCreatedAt(sep).SaveX(ctx)
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(b.ID).SetMonthlySalary(d("30000")).SaveX(ctx)

	// Loans: one current, one ended before the period, one inactive.
	current := client.EmployeeLoan.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetIsActive(true).
		SetPrincipalAmount(d("10000")).SetAmountRepaid(d("9500")).SetMonthlyInstallment(d("1000")).SetStartDate(before).SaveX(ctx)
	client.EmployeeLoan.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetIsActive(true).
		SetPrincipalAmount(d("5000")).SetMonthlyInstallment(d("500")).SetStartDate(before).SetEndDate(before).SaveX(ctx)
	client.EmployeeLoan.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetIsActive(false).
		SetPrincipalAmount(d("5000")).SetMonthlyInstallment(d("500")).SaveX(ctx)

	// Advance on a 4-installment repay option (installment 2000), one issued after the period.
	ro := client.RepayOption.Create().SetTenantID(tenant).SetAmount(d("8000")).SetNoOfInstallments(4).SaveX(ctx)
	adv := client.Advance.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetIsActive(true).
		SetAmountIssued(d("8000")).SetRepayOptionID(ro.ID).SetIssueDate(before).SaveX(ctx)
	client.Advance.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetIsActive(true).
		SetAmountIssued(d("3000")).SetRepayOptionID(ro.ID).SetIssueDate(after).SaveX(ctx)

	ld := client.LossAndDamage.Create().SetTenantID(tenant).SetEmployeeID(b.ID).SetIsActive(true).
		SetDamageAmount(d("1200")).SetRepayOptionID(ro.ID).SaveX(ctx)
	sp := client.StaffPurchaseDeduction.Create().SetTenantID(tenant).SetEmployeeID(b.ID).SetIsActive(true).
		SetOrigin(staffpurchasededuction.OriginCreditSale).SetSourceKey("pos:1").
		SetPrincipal(d("900")).SetAmountRecovered(d("600")).SetInstallmentAmount(d("500")).SaveX(ctx)

	comp := client.PayrollComponent.Create().SetTenantID(tenant).SetTitle("Housing").SaveX(ctx)
	client.EmployeeBenefit.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetComponentID(comp.ID).
		SetNonCash(true).SetAmount(d("4000")).SaveX(ctx)
	client.EmployeeBenefit.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetNonCash(true).
		SetAmount(d("700")).SetEffectiveDate(after).SaveX(ctx) // not yet effective
	client.EmployeeBenefit.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetNonCash(false).SetAmount(d("999")).SaveX(ctx)

	// Another tenant's rows for the same employee ids never leak in.
	other := uuid.New()
	client.EmployeeLoan.Create().SetTenantID(other).SetEmployeeID(a.ID).SetIsActive(true).
		SetPrincipalAmount(d("1")).SetMonthlyInstallment(d("1")).SaveX(ctx)

	svc := NewService(client, nil)
	pre, err := svc.loadRunInputs(ctx, tenant, []*ent.Employee{a, b, noSalary})
	if err != nil {
		t.Fatal(err)
	}

	p := RunParams{TenantID: tenant, Period: sep, RecoverAdvances: true}
	inA, itemsA, err := svc.buildEmployeeInput(p, a, pre)
	if err != nil {
		t.Fatal(err)
	}
	if !inA.GrossPay.Equal(d("60000")) || inA.TaxCategory != "secondary" {
		t.Errorf("A salary = %s %s, want the newest (60000, secondary)", inA.GrossPay, inA.TaxCategory)
	}
	if len(inA.Loans) != 1 || len(itemsA.Loans) != 1 || !itemsA.Loans[0].Amount.Equal(d("500")) {
		t.Errorf("A loans = %+v / %+v, want only the current loan recovering its 500 balance", inA.Loans, itemsA.Loans)
	}
	if len(inA.Advances) != 1 || !inA.Advances[0].Installment.Equal(d("2000")) || len(itemsA.Advances) != 1 {
		t.Errorf("A advances = %+v, want one at 2000 a period", inA.Advances)
	}
	if !inA.NonCashBenefits.Equal(d("4000")) || len(itemsA.Benefits) != 1 || itemsA.Benefits[0].Label != "Housing" {
		t.Errorf("A benefits = %s %+v, want 4000 labelled Housing", inA.NonCashBenefits, itemsA.Benefits)
	}
	recovered := map[string]uuid.UUID{}
	for _, r := range itemsA.Recoveries {
		recovered[r.Type] = r.ID
	}
	if recovered["loan"] != current.ID || recovered["advance"] != adv.ID {
		t.Errorf("A recoveries = %+v", itemsA.Recoveries)
	}

	// Without advance recovery the advance is still an input but nothing is recovered.
	_, noAdv, _ := svc.buildEmployeeInput(RunParams{TenantID: tenant, Period: sep}, a, pre)
	if len(noAdv.Advances) != 0 {
		t.Errorf("advances recovered without RecoverAdvances: %+v", noAdv.Advances)
	}

	inB, itemsB, err := svc.buildEmployeeInput(p, b, pre)
	if err != nil {
		t.Fatal(err)
	}
	if len(inB.LossDamages) != 1 || !inB.LossDamages[0].Installment.Equal(d("2000")) || !itemsB.LossDamages[0].Amount.Equal(d("1200")) {
		t.Errorf("B loss and damage = %+v %+v, want 1200 recovered (capped at outstanding)", inB.LossDamages, itemsB.LossDamages)
	}
	if len(itemsB.StaffPurchases) != 1 || !itemsB.StaffPurchases[0].Amount.Equal(d("300")) {
		t.Errorf("B staff purchase = %+v, want the 300 still owed", itemsB.StaffPurchases)
	}
	ids := map[uuid.UUID]bool{}
	for _, r := range itemsB.Recoveries {
		ids[r.ID] = true
	}
	if !ids[ld.ID] || !ids[sp.ID] {
		t.Errorf("B recoveries = %+v", itemsB.Recoveries)
	}

	if _, _, err := svc.buildEmployeeInput(p, noSalary, pre); err == nil {
		t.Error("an employee without an active salary must fail")
	}
}
