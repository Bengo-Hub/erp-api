package payrollsettings

import (
	"testing"
	"time"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

func dp(s string) *decimal.Decimal {
	d := decimal.RequireFromString(s)
	return &d
}

func tr(cat, code, rate string, min, max *decimal.Decimal, from time.Time) treasury.StatutoryRate {
	return treasury.StatutoryRate{Category: cat, Code: code, Rate: decimal.RequireFromString(rate),
		ThresholdMin: min, ThresholdMax: max, EffectiveFrom: from, IsActive: true}
}

// Treasury's reference (as seeded in treasury-api) maps onto contiguous formula bands.
func TestMapTreasuryRates(t *testing.T) {
	jul23 := time.Date(2023, 7, 1, 0, 0, 0, 0, time.UTC)
	jan24 := time.Date(2024, 1, 1, 0, 0, 0, 0, time.UTC)
	feb26 := time.Date(2026, 2, 1, 0, 0, 0, 0, time.UTC)
	rates := []treasury.StatutoryRate{
		tr("paye", "PAYE_BAND_2", "25", dp("24001"), dp("32333"), jul23),
		tr("paye", "PAYE_BAND_1", "10", dp("0"), dp("24000"), jul23),
		tr("paye", "PAYE_BAND_3", "30", dp("32334"), dp("500000"), jul23),
		tr("paye", "PAYE_PERSONAL_RELIEF", "2400", nil, nil, jan24),
		tr("nssf", "NSSF_TIER1", "6", nil, dp("9000"), feb26),
		tr("nssf", "NSSF_TIER2", "6", dp("9000"), dp("108000"), feb26),
		tr("shif", "SHIF_RATE", "2.75", dp("300"), nil, jul23),
		tr("vat", "VAT_STANDARD", "16", nil, nil, jul23),
		{Category: "housing_levy", Code: "HOUSING_LEVY", Rate: decimal.RequireFromString("1.5"), EffectiveFrom: jul23, IsActive: false},
	}
	got := map[string]treasuryFormula{}
	for _, f := range mapTreasuryRates(rates) {
		got[f.category] = f
	}
	if _, ok := got["housing_levy"]; ok {
		t.Error("inactive treasury rows must be ignored")
	}
	paye := got["primary"]
	if len(paye.items) != 3 || !paye.items[1].AmountFrom.Equal(decimal.NewFromInt(24000)) || !paye.items[2].AmountFrom.Equal(decimal.NewFromInt(32333)) {
		t.Errorf("PAYE bands must be contiguous: %+v", paye.items)
	}
	if paye.personalRelief == nil || !paye.personalRelief.Equal(decimal.NewFromInt(2400)) || !paye.effectiveFrom.Equal(jul23) {
		t.Errorf("PAYE relief/date: %+v", paye)
	}
	// The relief's later date moves the version only when the relief value changed.
	if !paye.versionDate(decimal.NewFromInt(2400)).Equal(jul23) {
		t.Error("an unchanged relief must not move the version date")
	}
	if !paye.versionDate(decimal.NewFromInt(2000)).Equal(jan24) {
		t.Error("a changed relief takes its own effective date")
	}
	nssf := got["social_security_fund"]
	if len(nssf.items) != 2 || !nssf.items[1].AmountTo.Equal(decimal.NewFromInt(108000)) || !nssf.effectiveFrom.Equal(feb26) {
		t.Errorf("NSSF tiers: %+v", nssf)
	}
	shif := got["shif"]
	if len(shif.items) != 1 || !shif.items[0].DeductPercentage.Equal(decimal.RequireFromString("2.75")) || !shif.items[0].AmountTo.IsZero() {
		t.Errorf("SHIF: %+v", shif.items)
	}
}

func TestSameItems(t *testing.T) {
	a := []FormulaItemInput{{AmountFrom: decimal.Zero, AmountTo: decimal.Zero, DeductPercentage: decimal.RequireFromString("2.75")}}
	b := []FormulaItemInput{{AmountFrom: decimal.Zero, AmountTo: decimal.Zero, DeductPercentage: decimal.RequireFromString("2.750")}}
	if !sameItems(a, b) {
		t.Error("equal decimals in another scale are the same")
	}
	b[0].DeductPercentage = decimal.NewFromInt(3)
	if sameItems(a, b) {
		t.Error("a rate change must be detected")
	}
}
