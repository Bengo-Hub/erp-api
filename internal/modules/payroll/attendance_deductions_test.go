package payroll

import (
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

func TestWeekdaysAndDailyRate(t *testing.T) {
	sep := time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)
	if n := weekdaysIn(sep); n != 22 {
		t.Fatalf("weekdays in September 2026 = %d, want 22", n)
	}
	if r := dailyRate(decimal.NewFromInt(22000), sep); !r.Equal(decimal.NewFromInt(1000)) {
		t.Fatalf("daily rate = %s, want 1000", r)
	}
	if r := dailyRate(decimal.Zero, sep); !r.IsZero() {
		t.Fatalf("no salary gives a zero rate, got %s", r)
	}
}

func TestPriceLate(t *testing.T) {
	daily, hours := decimal.NewFromInt(1000), decimal.NewFromInt(8)
	// 10 minutes is within the 15-minute threshold; -1 is late with no shift to measure.
	arrivals := []int{10, 30, 60, -1}
	rule := func(typ, value string) penaltyRule {
		return penaltyRule{Type: typ, Value: decimal.RequireFromString(value), Threshold: 15}
	}
	cases := []struct {
		rule  penaltyRule
		want  string
		occ   int
		price bool
	}{
		{rule("fixed", "200"), "600", 3, true},
		{rule("percent_daily", "10"), "300", 3, true}, // 10% of 1000 x 3
		{rule("per_minute", "0"), "187.5", 3, true},   // 90 minutes x 1000/8/60
		{rule("per_minute", "2"), "375", 3, true},     // doubled
		{rule("warning", "0"), "0", 3, false},
		{rule("something_else", "5"), "0", 3, false},
	}
	for _, c := range cases {
		got, ok := priceLate(c.rule, daily, hours, arrivals)
		if ok != c.price || (ok && !got.Amount.Equal(decimal.RequireFromString(c.want))) || got.Occurrences != c.occ {
			t.Errorf("%s: got %s (ok=%v, occ=%d), want %s (ok=%v)", c.rule.Type, got.Amount, ok, got.Occurrences, c.want, c.price)
		}
		if ok && got.Basis == "" {
			t.Errorf("%s: basis is empty", c.rule.Type)
		}
	}
	if _, ok := priceLate(rule("fixed", "200"), daily, hours, []int{5, 15}); ok {
		t.Error("arrivals within the threshold must not be priced")
	}
}

func TestPickRule(t *testing.T) {
	dept, outlet := uuid.New(), uuid.New()
	tenantWide := &ent.AttendanceRule{ID: uuid.New(), Priority: 100}
	tenantHigh := &ent.AttendanceRule{ID: uuid.New(), Priority: 200}
	branch := &ent.AttendanceRule{ID: uuid.New(), BranchID: &outlet, Priority: 1}
	department := &ent.AttendanceRule{ID: uuid.New(), DepartmentID: &dept, Priority: 1}
	other := uuid.New()
	otherDept := &ent.AttendanceRule{ID: uuid.New(), DepartmentID: &other, Priority: 999}
	rules := []*ent.AttendanceRule{tenantWide, tenantHigh, branch, department, otherDept}

	if got := pickRule(rules, &dept, &outlet); got != department {
		t.Errorf("department rule should win, got %v", got.ID)
	}
	if got := pickRule(rules, nil, &outlet); got != branch {
		t.Errorf("branch rule should win without a department match, got %v", got.ID)
	}
	if got := pickRule(rules, nil, nil); got != tenantHigh {
		t.Errorf("highest-priority tenant-wide rule should win, got %v", got.ID)
	}
	if got := pickRule(nil, &dept, nil); got != nil {
		t.Errorf("no rules gives nil, got %v", got)
	}
}
