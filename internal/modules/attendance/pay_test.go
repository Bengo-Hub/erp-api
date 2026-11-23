package attendance

import (
	"testing"

	"github.com/shopspring/decimal"
)

func TestPayableDay(t *testing.T) {
	d := decimal.RequireFromString
	if ot, hol := payableDay(d("8"), d("3"), false, false, decimal.Zero); !ot.Equal(d("3")) || !hol.IsZero() {
		t.Fatalf("ordinary day: ot %s hol %s", ot, hol)
	}
	if ot, _ := payableDay(d("8"), d("3"), false, true, d("2")); !ot.Equal(d("2")) {
		t.Fatalf("approval caps overtime at 2, got %s", ot)
	}
	if ot, _ := payableDay(d("8"), d("3"), false, true, decimal.Zero); !ot.IsZero() {
		t.Fatalf("no approval pays no overtime, got %s", ot)
	}
	if ot, hol := payableDay(d("6"), d("1"), true, true, decimal.Zero); !ot.IsZero() || !hol.Equal(d("7")) {
		t.Fatalf("holiday: ot %s hol %s", ot, hol)
	}
}

func TestPayableTimeAmount(t *testing.T) {
	d := decimal.RequireFromString
	p := PayableTime{OvertimeHours: d("10"), OvertimeMultiplier: d("1.5"), HolidayHours: d("8"), HolidayMultiplier: d("2"), MonthlyHours: d("195")}
	ot, hol := p.Amount(d("39000")) // 200 an hour
	if !ot.Equal(d("3000")) || !hol.Equal(d("3200")) {
		t.Fatalf("overtime %s holiday %s", ot, hol)
	}
	if ot, hol := (PayableTime{}).Amount(d("39000")); !ot.IsZero() || !hol.IsZero() {
		t.Fatal("no basis pays nothing")
	}
}
