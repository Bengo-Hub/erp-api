package reports

import (
	"context"
	"errors"
	"testing"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// TestIntegration_RemittanceSchedule: a check-off schedule (SACCO, HELB, union dues) lists, for one
// deduction and one period, what each employee actually had deducted with their member or account
// number from their assignment. The part net pay or the deduction limits left unrecovered is not
// remitted, so it is not on the schedule.
func TestIntegration_RemittanceSchedule(t *testing.T) {
	fx := newReturnsFixture(t)
	ctx := context.Background()
	d := decimal.RequireFromString
	sacco := fx.client.PayrollComponent.Create().SetTenantID(fx.tenant).SetTitle("Mwalimu SACCO").SaveX(ctx)
	helb := fx.client.PayrollComponent.Create().SetTenantID(fx.tenant).SetTitle("HELB").SaveX(ctx)
	line := func(p *ent.Payslip, section, code string, comp *ent.PayrollComponent, amount string) {
		fx.client.PayslipLine.Create().SetTenantID(fx.tenant).SetPayslipID(p.ID).SetSection(section).SetCode(code).
			SetLabel(comp.Title).SetComponentID(comp.ID).SetCashAmount(d(amount)).SaveX(ctx)
	}
	line(fx.octA, "deduction_after_tax", "sacco", sacco, "2000")
	line(fx.octA, "deduction_after_tax", "helb", helb, "1500")
	line(fx.octB, "deduction_after_tax", "sacco", sacco, "1000")
	line(fx.octB, "deduction_shortfall", "sacco", sacco, "400") // not deducted: never remitted
	fx.client.EmployeeBenefit.Create().SetTenantID(fx.tenant).SetEmployeeID(fx.amina.ID).SetComponentID(sacco.ID).
		SetAmount(d("2000")).SetMetadata(map[string]any{"reference": "SAC-001"}).SaveX(ctx)
	fx.client.EmployeeBenefit.Create().SetTenantID(fx.tenant).SetEmployeeID(fx.amina.ID).SetComponentID(helb.ID).
		SetAmount(d("1500")).SetMetadata(map[string]any{"reference": "HELB-77"}).SaveX(ctx)
	svc := NewService(fx.client)

	f := fx.octF
	f.Deduction = "sacco"
	rep, err := svc.Remittance(ctx, fx.tenant, f)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 2 {
		t.Fatalf("sacco rows = %d, want 2: %v", len(rep.Rows), rep.Rows)
	}
	byName := map[string]map[string]any{}
	for _, r := range rep.Rows {
		assertKeys(t, "remittance", r, rep.Columns...)
		byName[r["employee_name"].(string)] = r
	}
	if a := byName["Amina Otieno"]; a["member_number"] != "SAC-001" || a["amount"] != "2000.00" || a["national_id"] != "" || a["staff_number"] != "E1" {
		t.Errorf("amina = %v", a)
	}
	if b := byName["Brian"]; b["member_number"] != "" || b["amount"] != "1000.00" {
		t.Errorf("brian (no reference, shortfall excluded) = %v", b)
	}
	if rep.Totals["amount"] != "3000.00" || rep.Totals["count"] != 2 || rep.Totals["deduction"] != "Mwalimu SACCO" {
		t.Errorf("totals = %v", rep.Totals)
	}

	// The same schedule by component id; HELB is its own schedule.
	f.Deduction = helb.ID.String()
	rep, err = svc.Remittance(ctx, fx.tenant, f)
	if err != nil {
		t.Fatal(err)
	}
	if len(rep.Rows) != 1 || rep.Rows[0]["member_number"] != "HELB-77" || rep.Rows[0]["amount"] != "1500.00" {
		t.Errorf("helb = %v", rep.Rows)
	}

	// Another tenant's component id finds nothing; no deduction named is a bad request.
	f.Deduction = uuid.NewString()
	if rep, err = svc.Remittance(ctx, fx.tenant, f); err != nil || len(rep.Rows) != 0 {
		t.Errorf("unknown deduction = %v, %v", rep, err)
	}
	f.Deduction = ""
	if _, err = svc.Remittance(ctx, fx.tenant, f); !errors.Is(err, ErrBadFilter) {
		t.Errorf("no deduction err = %v, want ErrBadFilter", err)
	}
}
