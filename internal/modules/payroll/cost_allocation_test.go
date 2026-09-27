package payroll

import (
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

func sumShares(s []costShare) decimal.Decimal {
	t := decimal.Zero
	for _, x := range s {
		t = t.Add(x.Amount)
	}
	return t
}

var (
	projA  = uuid.MustParse("00000000-0000-0000-0000-00000000aa01")
	projB  = uuid.MustParse("00000000-0000-0000-0000-00000000aa02")
	ccDept = uuid.MustParse("00000000-0000-0000-0000-00000000cc01")
	ccProj = uuid.MustParse("00000000-0000-0000-0000-00000000cc02")
)

func TestSplitGross(t *testing.T) {
	fixed := dec("30000")
	cases := []struct {
		name  string
		gross string
		rules []allocRule
		want  []string // amounts in order
	}{
		{"no allocation: all to the department", "100000", nil, []string{"100000"}},
		{"single project 100%", "100000", []allocRule{{ProjectID: projA, Percent: dec("100")}}, []string{"100000"}},
		{"60/40 split", "100000", []allocRule{{ProjectID: projA, Percent: dec("60")}, {ProjectID: projB, Percent: dec("40")}}, []string{"60000", "40000"}},
		{"part allocated, rest to the department", "100000", []allocRule{{ProjectID: projA, Percent: dec("25")}}, []string{"25000", "75000"}},
		{"fixed amount taken first", "100000", []allocRule{{ProjectID: projA, Percent: dec("50")}, {ProjectID: projB, Fixed: &fixed}}, []string{"30000", "50000", "20000"}},
		{"over-allocation is capped at gross", "100000", []allocRule{{ProjectID: projA, Percent: dec("80")}, {ProjectID: projB, Percent: dec("50")}}, []string{"80000", "20000"}},
		{"zero percent rules are ignored", "1000", []allocRule{{ProjectID: projA, Percent: dec("0")}}, []string{"1000"}},
		{"rounding still adds up", "1000.01", []allocRule{{ProjectID: projA, Percent: dec("33.33")}, {ProjectID: projB, Percent: dec("33.33")}}, []string{"333.30", "333.30", "333.41"}},
	}
	for _, tc := range cases {
		got := splitGross(dec(tc.gross), tc.rules, &ccDept)
		if len(got) != len(tc.want) {
			t.Fatalf("%s: got %d shares %+v, want %v", tc.name, len(got), got, tc.want)
		}
		for i, w := range tc.want {
			if !got[i].Amount.Equal(dec(w)) {
				t.Errorf("%s: share %d = %s, want %s", tc.name, i, got[i].Amount, w)
			}
		}
		if !sumShares(got).Equal(dec(tc.gross)) {
			t.Errorf("%s: shares add to %s, want gross %s", tc.name, sumShares(got), tc.gross)
		}
	}
	if splitGross(decimal.Zero, nil, nil) != nil {
		t.Error("no gross, no shares")
	}
}

func TestSplitGrossCostCenters(t *testing.T) {
	got := splitGross(dec("100"), []allocRule{
		{ProjectID: projA, Percent: dec("50"), CostCenterID: &ccProj},
		{ProjectID: projB, Percent: dec("20")},
	}, &ccDept)
	if *got[0].CostCenterID != ccProj {
		t.Error("an allocation's own cost center wins")
	}
	if *got[1].CostCenterID != ccDept {
		t.Error("an allocation without a cost center falls back to the department's")
	}
	if got[2].ProjectID != nil || *got[2].CostCenterID != ccDept {
		t.Error("the unallocated rest has no project and the department's cost center")
	}
	if rest := splitGross(dec("100"), nil, nil); rest[0].CostCenterID != nil {
		t.Error("no department cost center: untagged overhead")
	}
}

func TestMergeShares(t *testing.T) {
	a, b := projA, projB
	got := mergeShares([]costShare{
		{ProjectID: &a, Amount: dec("10")},
		{ProjectID: &b, Amount: dec("5")},
		{ProjectID: &a, Amount: dec("7")},
		{Amount: dec("1")},
		{Amount: dec("2")},
	})
	if len(got) != 3 || !got[0].Amount.Equal(dec("17")) || !got[2].Amount.Equal(dec("3")) {
		t.Fatalf("got %+v", got)
	}
}

func TestRuleInForce(t *testing.T) {
	period := time.Date(2026, 3, 15, 0, 0, 0, 0, time.UTC)
	d := func(s string) *time.Time { t, _ := time.Parse("2006-01-02", s); return &t }
	cases := []struct {
		start, end *time.Time
		want       bool
	}{
		{nil, nil, true},
		{d("2026-03-31"), nil, true},  // starts within the month
		{d("2026-04-01"), nil, false}, // starts after
		{nil, d("2026-03-01"), true},  // ends within
		{nil, d("2026-02-28"), false}, // ended before
	}
	for i, c := range cases {
		if got := ruleInForce(c.start, c.end, period); got != c.want {
			t.Errorf("case %d: got %v, want %v", i, got, c.want)
		}
	}
}

func TestAllocationsPayload(t *testing.T) {
	a := projA
	p := allocationsPayload([]costShare{{ProjectID: &a, CostCenterID: &ccDept, Amount: dec("12.5")}, {Amount: dec("1")}})
	if p[0]["amount"] != "12.50" || p[0]["project_id"] != projA.String() || p[0]["cost_center_id"] != ccDept.String() {
		t.Fatalf("got %+v", p[0])
	}
	if _, has := p[1]["project_id"]; has {
		t.Error("unallocated share carries no project")
	}
}

func TestMergeOptions(t *testing.T) {
	got := mergeOptions([]uuid.UUID{projA, uuid.Nil, projB}, []uuid.UUID{projA})
	if len(got) != 2 {
		t.Fatalf("got %+v", got)
	}
}
