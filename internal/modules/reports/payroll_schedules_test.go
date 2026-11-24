package reports

import (
	"testing"
	"time"

	"github.com/shopspring/decimal"
)

// The variance report compares a month with the calendar month before it (October has 31
// days, so a same-length window would start on 31 August) and a year with the year before.
func TestPreviousPeriod(t *testing.T) {
	month, _ := ResolvePeriod(2026, 10, nil)
	if p := previousPeriod(month); !p.Start.Equal(time.Date(2026, 9, 1, 0, 0, 0, 0, time.UTC)) || !p.End.Equal(month.Start) {
		t.Fatalf("previous month = %v .. %v", p.Start, p.End)
	}
	year, _ := ResolvePeriod(2026, 0, nil)
	if p := previousPeriod(year); !p.Start.Equal(time.Date(2025, 1, 1, 0, 0, 0, 0, time.UTC)) {
		t.Fatalf("previous year starts %v", p.Start)
	}
}

func TestVarianceRow(t *testing.T) {
	d := decimal.RequireFromString
	r := varianceRow("Net Pay", d("110"), d("100"))
	if r["variance_amount"] != "10.00" || r["variance_percent"] != "10.00" || r["variance_type"] != "Increase" {
		t.Fatalf("row = %v", r)
	}
	if r := varianceRow("PAYE", d("5"), d("0")); r["variance_percent"] != nil || r["variance_type"] != "New" {
		t.Fatalf("new row = %v", r)
	}
	if r := varianceRow("PAYE", d("0"), d("0")); r["variance_type"] != "No change" {
		t.Fatalf("flat row = %v", r)
	}
}
