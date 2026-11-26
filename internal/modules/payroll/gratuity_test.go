package payroll

import (
	"testing"
	"time"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// facts picks the contract in force, sums the contract's earlier pay without earlier gratuity, and
// carries what was already excluded.
func TestGratuityHistoryFacts(t *testing.T) {
	at := func(y int, m time.Month) time.Time { return time.Date(y, m, 1, 0, 0, 0, 0, time.UTC) }
	ptr := func(v time.Time) *time.Time { return &v }
	dec := decimal.RequireFromString
	h := &gratuityHistory{
		contracts: []*ent.Contract{
			{StartDate: ptr(at(2020, 1)), EndDate: ptr(at(2023, 7).AddDate(0, 0, -1))},
			{StartDate: ptr(at(2023, 7)), EndDate: ptr(at(2026, 7).AddDate(0, 0, 30))},
		},
		gross: []paidMonth{
			{at(2023, 6), dec("90000")}, // the old contract: not counted
			{at(2023, 7), dec("100000")},
			{at(2026, 6), dec("150000")}, // includes 50,000 gratuity
		},
		paid:     []paidMonth{{at(2026, 6), dec("50000")}},
		excluded: []paidMonth{{at(2026, 6), dec("50000")}},
	}
	f := h.facts(at(2026, 7), dec("100000"), false)
	if f.ContractStart == nil || !f.ContractStart.Equal(at(2023, 7)) {
		t.Fatalf("contract start %v, want 2023-07-01", f.ContractStart)
	}
	if !f.Emoluments.Equal(dec("300000")) || !f.AlreadyExcluded.Equal(dec("50000")) {
		t.Errorf("emoluments %s excluded %s, want 300000 and 50000", f.Emoluments, f.AlreadyExcluded)
	}
	if f.ServiceStart == nil || !f.ServiceStart.Equal(at(2020, 1)) {
		t.Errorf("service start %v, want 2020-01-01", f.ServiceStart)
	}
}

func TestGratuityExcluded(t *testing.T) {
	day := func(y int, m time.Month, d int) *time.Time {
		v := time.Date(y, m, d, 0, 0, 0, 0, time.UTC)
		return &v
	}
	dec := decimal.RequireFromString
	aug26 := time.Date(2026, 8, 1, 0, 0, 0, 0, time.UTC)
	jun26 := time.Date(2026, 6, 1, 0, 0, 0, 0, time.UTC)
	threeYears := gratuityFacts{ContractStart: day(2023, 8, 1), ContractEnd: day(2026, 7, 31), Emoluments: dec("3600000")}

	cases := []struct {
		name   string
		status string
		amount string
		period time.Time
		facts  gratuityFacts
		want   string
	}{
		{"contract rule: under 31% fully excluded", TaxableGratuity, "1000000", aug26, threeYears, "1000000"},
		{"contract rule: capped at 31% of emoluments", TaxableGratuity, "1500000", aug26, threeYears, "1116000"},
		{"contract rule: earlier exclusion uses up the room", TaxableGratuity, "500000", aug26,
			gratuityFacts{ContractStart: threeYears.ContractStart, ContractEnd: threeYears.ContractEnd, Emoluments: dec("3600000"), AlreadyExcluded: dec("1000000")}, "116000"},
		{"contract rule: not before 1 July 2026", TaxableGratuity, "1000000", jun26, threeYears, "0"},
		{"contract rule: under three years", TaxableGratuity, "100000", aug26,
			gratuityFacts{ContractStart: day(2024, 1, 1), ContractEnd: day(2026, 7, 31), Emoluments: dec("3000000")}, "0"},
		{"contract rule: open-ended contract counts to the period end", TaxableGratuity, "100000", aug26,
			gratuityFacts{ContractStart: day(2023, 8, 1), Emoluments: dec("3700000")}, "100000"},
		{"contract rule: no contract", TaxableGratuity, "100000", aug26, gratuityFacts{Emoluments: dec("3600000")}, "0"},
		{"pension rule: 360,000 per completed year", TaxableGratuityPension, "1000000", aug26,
			gratuityFacts{ServiceStart: day(2024, 6, 15)}, "720000"},
		{"pension rule: not for a pension scheme member", TaxableGratuityPension, "100000", aug26,
			gratuityFacts{ServiceStart: day(2020, 1, 1), PensionMember: true}, "0"},
		{"plain taxable earning", "taxable", "100000", aug26, threeYears, "0"},
	}
	for _, c := range cases {
		got := gratuityExcluded(c.status, dec(c.amount), c.period, c.facts)
		if !got.Equal(dec(c.want)) {
			t.Errorf("%s: got %s want %s", c.name, got, c.want)
		}
	}
}
