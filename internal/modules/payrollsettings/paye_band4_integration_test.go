package payrollsettings

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformula"
	"github.com/Bengo-Hub/erp-api/internal/ent/payrollformulaitem"
	"github.com/Bengo-Hub/erp-api/internal/ent/schema"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll/payrollengine"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

func TestIntegration_PAYEBand4Correction(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	svc := NewService(client, uuid.New())
	seedPlatform(t, ctx, svc)
	sys := svc.SystemTenant()
	d := decimal.RequireFromString

	// The platform formula as deployed before the correction, with a stored deduction order.
	old := client.PayrollFormula.Query().Where(payrollformula.TenantID(sys), payrollformula.TypeEQ("income"),
		payrollformula.CategoryEQ("primary")).OnlyX(ctx)
	client.PayrollFormulaItem.Update().Where(payrollformulaitem.FormulaID(old.ID), payrollformulaitem.AmountTo(d("800000"))).
		SetAmountTo(d("799999")).ExecX(ctx)
	client.PayrollFormulaItem.Update().Where(payrollformulaitem.FormulaID(old.ID), payrollformulaitem.AmountFrom(d("800000"))).
		SetAmountFrom(d("799999")).ExecX(ctx)
	var order []schema.DeductionPhase
	for _, p := range payrollengine.DefaultDeductionOrder() {
		order = append(order, schema.DeductionPhase{Phase: p.Name, Components: p.Components})
	}
	client.PayrollFormula.UpdateOneID(old.ID).SetDeductionOrder(order).ExecX(ctx)

	// A tenant that customised PAYE before the correction.
	tenant, custom := uuid.New(), uuid.New()
	own, err := svc.CustomiseFormula(ctx, custom, old.ID)
	if err != nil {
		t.Fatal(err)
	}

	paye := func(who uuid.UUID, y int, m time.Month) decimal.Decimal {
		t.Helper()
		cfg, err := svc.BuildEngineConfig(ctx, who, *day(y, m, 1), true)
		if err != nil {
			t.Fatal(err)
		}
		if len(cfg.DeductionOrder) != len(order) {
			t.Fatalf("deduction order lost: %v", cfg.DeductionOrder)
		}
		tax, err := payrollengine.CalculateIncomeTax(cfg.Income, d("900000"))
		if err != nil {
			t.Fatal(err)
		}
		return tax
	}
	novBefore := paye(tenant, 2026, time.November)

	if applied, err := EnsurePAYEBand4(ctx, client, sys); err != nil || !applied {
		t.Fatalf("first run = %v, %v; want applied", applied, err)
	}
	if applied, err := EnsurePAYEBand4(ctx, client, sys); err != nil || applied {
		t.Fatalf("second run = %v, %v; want nothing to do", applied, err)
	}
	if n := client.PayrollFormula.Query().Where(payrollformula.TenantID(sys), payrollformula.TypeEQ("income"),
		payrollformula.CategoryEQ("primary")).CountX(ctx); n != 2 {
		t.Fatalf("platform PAYE versions = %d, want 2", n)
	}

	// November re-run: old limit. December: 1 shilling moves from 35% to 32.5%.
	if got := paye(tenant, 2026, time.November); !got.Equal(novBefore) || !got.Equal(d("277283.375")) {
		t.Errorf("November PAYE = %s, want the old 277283.375 (was %s)", got, novBefore)
	}
	if got := paye(tenant, 2026, time.December); !got.Equal(d("277283.35")) {
		t.Errorf("December PAYE = %s, want 277283.35", got)
	}
	// The customised copy is untouched and still used by its tenant.
	if got := paye(custom, 2026, time.December); !got.Equal(novBefore) {
		t.Errorf("customised tenant December PAYE = %s, want its own %s", got, novBefore)
	}
	if f := client.PayrollFormula.GetX(ctx, own.ID); !f.IsCurrent || f.EffectiveTo != nil {
		t.Errorf("tenant version changed: current=%v to=%v", f.IsCurrent, f.EffectiveTo)
	}
	// Personal relief carried over.
	cur := client.PayrollFormula.Query().Where(payrollformula.TenantID(sys), payrollformula.TypeEQ("income"),
		payrollformula.CategoryEQ("primary"), payrollformula.IsCurrent(true)).OnlyX(ctx)
	if !cur.PersonalRelief.Equal(d("2400")) || !cur.EffectiveFrom.Equal(PAYEBand4From) {
		t.Errorf("new version relief %s from %v", cur.PersonalRelief, cur.EffectiveFrom)
	}
	closed := client.PayrollFormula.GetX(ctx, old.ID)
	if closed.EffectiveTo == nil || closed.EffectiveTo.Format("2006-01-02") != "2026-11-30" {
		t.Errorf("old version closed %v, want 2026-11-30", closed.EffectiveTo)
	}

	// Treasury's reference now equals the platform bands; a newer restatement changes nothing.
	res, err := svc.SyncTreasuryRates(ctx, treasuryPAYE(time.Date(2027, 1, 1, 0, 0, 0, 0, time.UTC)))
	if err != nil || len(res) != 1 || res[0].Action != "unchanged" {
		t.Errorf("treasury sync = %+v %v, want unchanged", res, err)
	}
}

// treasuryPAYE is treasury's Kenya PAYE reference (lower bounds listed as 24,001 and so on).
func treasuryPAYE(from time.Time) []treasury.StatutoryRate {
	return []treasury.StatutoryRate{
		tr("paye", "PAYE_BAND_1", "10", dp("0"), dp("24000"), from),
		tr("paye", "PAYE_BAND_2", "25", dp("24001"), dp("32333"), from),
		tr("paye", "PAYE_BAND_3", "30", dp("32334"), dp("500000"), from),
		tr("paye", "PAYE_BAND_4", "32.5", dp("500001"), dp("800000"), from),
		tr("paye", "PAYE_BAND_5", "35", dp("800001"), nil, from),
	}
}

// The engine defaults and treasury's reference describe the same PAYE bands.
func TestKRADefaultsMatchTreasuryPAYE(t *testing.T) {
	want := mapTreasuryRates(treasuryPAYE(time.Date(2023, 7, 1, 0, 0, 0, 0, time.UTC)))[0].items
	var have []FormulaItemInput
	for _, b := range payrollengine.KRADefaults().Income.Bands {
		to := b.To
		if to.Equal(payrollengine.Inf) {
			to = decimal.Zero
		}
		have = append(have, FormulaItemInput{AmountFrom: b.From, AmountTo: to, DeductPercentage: b.Rate.Mul(hundred)})
	}
	if !sameItems(have, want) {
		t.Errorf("KRADefaults bands %+v differ from treasury %+v", have, want)
	}
}
