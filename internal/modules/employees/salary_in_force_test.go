package employees

import (
	"testing"
	"time"

	"github.com/shopspring/decimal"

	"github.com/Bengo-Hub/erp-api/internal/ent"
)

// Each month pays from the salary in force that month: an undated row until the first dated one
// starts, a scheduled raise from its month on, never a future one early, and inactive rows never.
func TestSalaryInForce(t *testing.T) {
	month := func(y int, m time.Month) *time.Time { v := time.Date(y, m, 1, 0, 0, 0, 0, time.UTC); return &v }
	created := time.Date(2026, 1, 1, 0, 0, 0, 0, time.UTC)
	row := func(amount int64, from *time.Time, active bool, createdAt time.Time) *ent.SalaryDetails {
		return &ent.SalaryDetails{MonthlySalary: decimal.NewFromInt(amount), EffectiveFrom: from, IsActive: active, CreatedAt: createdAt}
	}
	rows := []*ent.SalaryDetails{
		row(50000, nil, true, created),
		row(60000, month(2026, 12), true, created.Add(time.Hour)),
		row(70000, month(2027, 6), true, created.Add(2*time.Hour)),
		row(99000, month(2026, 12), false, created.Add(3*time.Hour)), // inactive
	}
	for _, c := range []struct {
		at   time.Time
		want int64
	}{
		{MonthEnd(*month(2026, 11)), 50000},
		{MonthEnd(*month(2026, 12)), 60000},
		{MonthEnd(*month(2027, 5)), 60000},
		{MonthEnd(*month(2027, 6)), 70000},
	} {
		got := SalaryInForce(rows, c.at)
		if got == nil || !got.MonthlySalary.Equal(decimal.NewFromInt(c.want)) {
			t.Errorf("%s: got %v, want %d", c.at.Format("2006-01"), got, c.want)
		}
	}
	if got := SalaryInForce([]*ent.SalaryDetails{row(60000, month(2027, 1), true, created)}, MonthEnd(*month(2026, 12))); got != nil {
		t.Errorf("a salary starting later applied early: %v", got.MonthlySalary)
	}
	// Two rows for the same month: the newer one.
	same := []*ent.SalaryDetails{row(1, month(2026, 12), true, created), row(2, month(2026, 12), true, created.Add(time.Minute))}
	if got := SalaryInForce(same, MonthEnd(*month(2026, 12))); !got.MonthlySalary.Equal(decimal.NewFromInt(2)) {
		t.Errorf("same month: got %s, want the newer row", got.MonthlySalary)
	}
}
