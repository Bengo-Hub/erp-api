package payroll

import (
	"context"
	"errors"
	"strings"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslip"
	"github.com/Bengo-Hub/erp-api/internal/ent/payslipline"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
)

// seedPlatformPayroll writes the KRA defaults (SHIF with its minimum) and the component catalogue
// under the platform tenant.
func seedPlatformPayroll(t *testing.T, ctx context.Context, client *ent.Client, set *payrollsettings.Service) {
	t.Helper()
	def := payrollengine.KRADefaults()
	hundred := decimal.NewFromInt(100)
	from := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	add := func(ftype, cat string, r *payrollengine.FormulaRates, relief bool) {
		in := payrollsettings.FormulaInput{Type: ftype, Category: cat, Title: ftype + " " + cat, EffectiveFrom: &from, IsCurrent: true}
		if relief {
			in.PersonalRelief = r.PersonalRelief
		}
		for _, b := range r.Bands {
			to := b.To
			if to.Equal(payrollengine.Inf) {
				to = decimal.Zero
			}
			in.Items = append(in.Items, payrollsettings.FormulaItemInput{AmountFrom: b.From, AmountTo: to, DeductAmount: b.Amount, DeductPercentage: b.Rate.Mul(hundred)})
		}
		emp, empr := r.EmployeePercentage.Mul(hundred), r.EmployerPercentage.Mul(hundred)
		if emp.IsZero() {
			emp = hundred
		}
		in.EmployeePercentage, in.EmployerPercentage = &emp, &empr
		if r.MinimumContribution.IsPositive() {
			m := r.MinimumContribution
			in.MinimumContribution = &m
		}
		if _, err := set.UpsertFormula(ctx, set.SystemTenant(), in); err != nil {
			t.Fatalf("seed %s/%s: %v", ftype, cat, err)
		}
	}
	add("income", "primary", def.Income, true)
	add("deduction", "social_security_fund", def.NSSF, false)
	add("deduction", "shif", def.SHIF, false)
	add("deduction", "housing_levy", def.HousingLevy, false)
	if _, err := payrollsettings.EnsurePlatformCatalogue(ctx, client, set.SystemTenant()); err != nil {
		t.Fatal(err)
	}
}

// Opt-in earnings and deductions assigned per employee reach the run: taxable and non-taxable
// earnings, a percentage of basic, start and end months, a component switched off after it was
// assigned, payslip lines under the component titles, and a deduction capped at net pay.
func TestIntegration_AssignedComponentsInRun(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	d := decimal.RequireFromString
	set := payrollsettings.NewService(client, uuid.New())
	seedPlatformPayroll(t, ctx, client, set)
	svc := NewService(client, set)
	tenant := uuid.New()

	comps, err := set.ResolveComponents(ctx, tenant, "")
	if err != nil {
		t.Fatal(err)
	}
	byCode := map[string]payrollsettings.ResolvedComponent{}
	for _, c := range comps {
		byCode[c.Code] = c
	}
	on := func(code string, active bool) uuid.UUID {
		id := byCode[code].Component.ID
		if _, err := set.SetComponentActive(ctx, tenant, id, active); err != nil {
			t.Fatalf("switch %s: %v", code, err)
		}
		return id
	}
	house, perDiem, sacco, helb, meal := on("house_allowance", true), on("per_diem", true), on("sacco", true), on("helb", true), on("meal_allowance", true)

	a := client.Employee.Create().SetTenantID(tenant).SetFirstName("Amina").SaveX(ctx)
	b := client.Employee.Create().SetTenantID(tenant).SetFirstName("Baraka").SaveX(ctx)
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(a.ID).SetMonthlySalary(d("100000")).SaveX(ctx)
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(b.ID).SetMonthlySalary(d("20000")).SaveX(ctx)

	month := func(y int, m time.Month) *time.Time { t := time.Date(y, m, 15, 0, 0, 0, 0, time.UTC); return &t }
	dec := func(s string) *decimal.Decimal { v := d(s); return &v }
	assign := func(emp uuid.UUID, in payrollsettings.AssignmentInput) {
		t.Helper()
		if _, err := set.SaveAssignment(ctx, tenant, emp, nil, in); err != nil {
			t.Fatalf("assign %s: %v", in.ComponentID, err)
		}
	}
	assign(a.ID, payrollsettings.AssignmentInput{ComponentID: house, Percentage: dec("10")}) // 10% of basic
	assign(a.ID, payrollsettings.AssignmentInput{ComponentID: perDiem, Amount: dec("3000")})
	assign(a.ID, payrollsettings.AssignmentInput{ComponentID: sacco, Amount: dec("2000"), Reference: "S-001",
		StartMonth: month(2026, 9), EndMonth: month(2026, 10)})
	assign(a.ID, payrollsettings.AssignmentInput{ComponentID: helb, Amount: dec("1500"), Reference: "HELB-9", StartMonth: month(2026, 11)})
	assign(a.ID, payrollsettings.AssignmentInput{ComponentID: meal, Amount: dec("999")})
	assign(b.ID, payrollsettings.AssignmentInput{ComponentID: sacco, Amount: dec("50000"), Reference: "S-002"})

	// Rules on assignment.
	if _, err := set.SaveAssignment(ctx, tenant, a.ID, nil, payrollsettings.AssignmentInput{ComponentID: helb, Amount: dec("1")}); err == nil ||
		!strings.Contains(err.Error(), "HELB account number") {
		t.Errorf("HELB without its account number = %v, want refused", err)
	}
	if _, err := set.SaveAssignment(ctx, tenant, a.ID, nil, payrollsettings.AssignmentInput{ComponentID: byCode["paye"].Component.ID, Amount: dec("1")}); !errors.Is(err, payrollsettings.ErrNotAssignable) {
		t.Errorf("assigning PAYE = %v, want ErrNotAssignable", err)
	}
	if _, err := set.SaveAssignment(ctx, tenant, a.ID, nil, payrollsettings.AssignmentInput{ComponentID: byCode["bonus"].Component.ID, Amount: dec("1")}); !errors.Is(err, payrollsettings.ErrNotAssignable) {
		t.Errorf("assigning a component the tenant has not switched on = %v, want ErrNotAssignable", err)
	}
	if _, err := set.SaveAssignment(ctx, tenant, a.ID, nil, payrollsettings.AssignmentInput{ComponentID: sacco, Amount: dec("1"), Reference: "S-001",
		StartMonth: month(2026, 10)}); err == nil {
		t.Error("a second SACCO assignment overlapping October must be refused")
	}

	// Switching Meal Allowance off stops it for everyone it was assigned to.
	on("meal_allowance", false)

	sep := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)
	out, err := svc.Run(ctx, RunParams{TenantID: tenant, Period: sep, Persist: true, RecoverAdvances: true})
	if err != nil {
		t.Fatal(err)
	}
	results := map[uuid.UUID]payrollengine.PayslipResult{}
	for _, l := range out {
		results[l.EmployeeID] = l.Result
	}

	cfg, err := set.BuildEngineConfig(ctx, tenant, sep, true)
	if err != nil {
		t.Fatal(err)
	}
	want, _ := payrollengine.Compute(cfg, payrollengine.EmployeeInput{GrossPay: d("100000"), TaxCategory: "primary",
		TaxableAllowances: d("10000"), NonTaxableEarnings: d("3000"),
		OtherDeductions: []payrollengine.Deduction{{Phase: payrollengine.PhaseAfterPAYE, Priority: 6, Amount: d("2000")}}})
	gotA := results[a.ID]
	if !gotA.GrossPay.Equal(d("113000")) || !gotA.NetPay.Equal(want.NetPay) || !gotA.OtherDeductions.Equal(d("2000")) {
		t.Errorf("A in September: gross %s net %s other %s, want 113000 / %s / 2000", gotA.GrossPay, gotA.NetPay, gotA.OtherDeductions, want.NetPay)
	}
	// Per diem is non-taxable: statutory and PAYE are on 110,000, not 113,000.
	if !gotA.SHIFOrNHIF.Equal(d("3025")) || !gotA.TaxablePay.Equal(want.TaxablePay) {
		t.Errorf("A SHIF %s taxable %s, want 3025 / %s", gotA.SHIFOrNHIF, gotA.TaxablePay, want.TaxablePay)
	}

	lines := payslipLines(t, ctx, client, tenant, a.ID, sep)
	for _, label := range []string{"House Allowance", "Per Diem", "SACCO Contribution"} {
		if _, ok := lines[label]; !ok {
			t.Errorf("A's September payslip has no %q line: %v", label, lineLabels(lines))
		}
	}
	for _, label := range []string{"HELB Loan Repayment", "Meal Allowance"} {
		if _, ok := lines[label]; ok {
			t.Errorf("A's September payslip must not show %q", label)
		}
	}
	if l := lines["House Allowance"]; l != nil && (!l.CashAmount.Equal(d("10000")) || !l.Taxable) {
		t.Errorf("house allowance line = %s taxable=%v, want 10000 taxable", l.CashAmount, l.Taxable)
	}
	if l := lines["Per Diem"]; l != nil && (l.Taxable || !l.TaxableAmount.IsZero()) {
		t.Errorf("per diem line must be non-taxable")
	}

	// B's SACCO (50,000) is larger than the net pay left: capped, the remainder on its own line.
	gotB := results[b.ID]
	if !gotB.NetPay.IsZero() || !gotB.DeductionShortfall.IsPositive() {
		t.Errorf("B: net %s shortfall %s, want 0 and a shortfall", gotB.NetPay, gotB.DeductionShortfall)
	}
	bLines := payslipLines(t, ctx, client, tenant, b.ID, sep)
	if l := bLines["SACCO Contribution (not deducted)"]; l == nil || !l.CashAmount.Equal(gotB.DeductionShortfall) {
		t.Errorf("B's shortfall line = %v, want %s", l, gotB.DeductionShortfall)
	}
	if l := bLines["SACCO Contribution"]; l == nil || !l.CashAmount.Equal(gotB.OtherDeductions) {
		t.Errorf("B's SACCO line = %v, want the %s taken", l, gotB.OtherDeductions)
	}

	// Pension: the assigned contribution gets the pension relief once, even when the salary tab
	// records the same contribution.
	pension := on("pension", true)
	c := client.Employee.Create().SetTenantID(tenant).SetFirstName("Chebet").SaveX(ctx)
	client.SalaryDetails.Create().SetTenantID(tenant).SetEmployeeID(c.ID).SetMonthlySalary(d("100000")).
		SetPensionContribution(d("5000")).SaveX(ctx)
	assign(c.ID, payrollsettings.AssignmentInput{ComponentID: pension, Amount: dec("5000"), Reference: "P-1"})
	client.PayrollRelief.Create().SetTenantID(set.SystemTenant()).SetType("Deductible").SetTitle("Pension Relief").
		SetActualAmount(true).SetFixedLimit(d("30000")).SetPercentage(d("100")).SetIsActive(true).SaveX(ctx)
	out, err = svc.Run(ctx, RunParams{TenantID: tenant, Period: sep, EmployeeIDs: []uuid.UUID{c.ID}})
	if err != nil || len(out) != 1 {
		t.Fatalf("pension run = %v %v", out, err)
	}
	if r := out[0].Result; !r.PensionDeduction.Equal(d("5000")) || !r.OtherDeductions.Equal(d("5000")) ||
		!r.DeductionsBeforeTax.Equal(d("8570")) || !r.TaxablePay.Equal(d("86430")) {
		t.Errorf("pension: relief %s taken %s before-tax %s taxable %s, want 5000/5000/8570/86430",
			r.PensionDeduction, r.OtherDeductions, r.DeductionsBeforeTax, r.TaxablePay)
	}

	// November: the SACCO assignment ended in October and HELB starts.
	nov := time.Date(2026, 11, 1, 0, 0, 0, 0, time.UTC)
	if _, err := svc.Run(ctx, RunParams{TenantID: tenant, Period: nov, Persist: true, EmployeeIDs: []uuid.UUID{a.ID}}); err != nil {
		t.Fatal(err)
	}
	lines = payslipLines(t, ctx, client, tenant, a.ID, nov)
	if _, ok := lines["SACCO Contribution"]; ok {
		t.Error("SACCO ended in October and must not apply in November")
	}
	if l, ok := lines["HELB Loan Repayment"]; !ok || !l.CashAmount.Equal(d("1500")) {
		t.Errorf("HELB from November = %v, want 1500", l)
	}
}

func payslipLines(t *testing.T, ctx context.Context, client *ent.Client, tenant, emp uuid.UUID, period time.Time) map[string]*ent.PayslipLine {
	t.Helper()
	ps := client.Payslip.Query().Where(payslip.TenantID(tenant), payslip.EmployeeID(emp), payslip.PaymentPeriod(period)).OnlyX(ctx)
	rows := client.PayslipLine.Query().Where(payslipline.PayslipID(ps.ID)).AllX(ctx)
	out := map[string]*ent.PayslipLine{}
	for _, r := range rows {
		out[r.Label] = r
	}
	return out
}

func lineLabels(m map[string]*ent.PayslipLine) []string {
	out := make([]string, 0, len(m))
	for k := range m {
		out = append(out, k)
	}
	return out
}
