package payroll

import (
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

func TestTripDays(t *testing.T) {
	start := time.Date(2026, 10, 1, 8, 0, 0, 0, time.UTC)
	cases := []struct {
		name string
		end  time.Time
		want float64
	}{
		{"same day", start.Add(6 * time.Hour), 1},
		{"exactly one day", start.Add(24 * time.Hour), 1},
		{"part of a second day", start.Add(26 * time.Hour), 2},
		{"three days", start.Add(70 * time.Hour), 3},
		{"end before start", start.Add(-time.Hour), 1},
	}
	for _, c := range cases {
		end := c.end
		if got := tripDays(&start, &end); got != c.want {
			t.Errorf("%s: got %v, want %v", c.name, got, c.want)
		}
	}
	if got := tripDays(nil, nil); got != 1 {
		t.Errorf("missing window: got %v, want 1", got)
	}
}

func TestPerDiemPolicyValidate(t *testing.T) {
	ok := PerDiemPolicy{Enabled: true, DailyRate: decimal.NewFromInt(2000), MinDistanceKm: 50}
	if err := ok.Validate(); err != nil {
		t.Fatalf("valid policy rejected: %v", err)
	}
	byGroup := PerDiemPolicy{Enabled: true, JobGroupRates: map[string]decimal.Decimal{uuid.NewString(): decimal.NewFromInt(3500)}}
	if err := byGroup.Validate(); err != nil {
		t.Fatalf("job group only policy rejected: %v", err)
	}
	bad := []PerDiemPolicy{
		{Enabled: true},
		{DailyRate: decimal.NewFromInt(-1)},
		{JobGroupRates: map[string]decimal.Decimal{"not-a-uuid": decimal.NewFromInt(1)}},
		{MinDistanceKm: -5},
	}
	for i, p := range bad {
		if err := p.Validate(); err == nil {
			t.Errorf("case %d: invalid policy accepted", i)
		}
	}
	if DefaultPerDiemPolicy().Enabled {
		t.Error("default policy must be disabled until HR sets a rate")
	}
}
