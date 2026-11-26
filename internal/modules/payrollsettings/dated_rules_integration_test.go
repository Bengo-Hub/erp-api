package payrollsettings

import (
	"context"
	"testing"
	"time"

	"github.com/google/uuid"
	"github.com/shopspring/decimal"
)

// The dated rules land on the platform once, the run config picks the version in force for the
// month, and the 2026 bill bands never apply.
func TestIntegration_DatedRules(t *testing.T) {
	client := testClient(t)
	ctx := context.Background()
	sys := uuid.New()
	svc := NewService(client, sys)
	seedPlatform(t, ctx, svc)

	n, err := EnsureDatedRules(ctx, client, sys)
	if err != nil {
		t.Fatal(err)
	}
	if again, err := EnsureDatedRules(ctx, client, sys); err != nil || again != 0 {
		t.Fatalf("second run created %d (%v), want 0", again, err)
	}
	if n != 4 {
		t.Errorf("created %d rules, want 4 (per diem, FBT Q3, FBT Q4, 2026 bill bands)", n)
	}

	month := func(y int, m time.Month) time.Time { return time.Date(y, m, 1, 0, 0, 0, 0, time.UTC) }
	tenant := uuid.New()
	for _, c := range []struct {
		period       time.Time
		perDiem, mkt string
		fbt          bool
	}{
		{month(2025, 6), "0", "", false},
		{month(2026, 6), "10000", "", false},
		{month(2026, 8), "10000", "8", true},
		{month(2026, 11), "10000", "9", true},
		{month(2027, 2), "10000", "9", true},
	} {
		cfg, err := svc.BuildEngineConfig(ctx, tenant, c.period, false)
		if err != nil {
			t.Fatal(err)
		}
		if !cfg.PerDiemDailyExempt.Equal(decimal.RequireFromString(c.perDiem)) {
			t.Errorf("%s per diem limit %s, want %s", c.period.Format("2006-01"), cfg.PerDiemDailyExempt, c.perDiem)
		}
		if (cfg.FBT != nil) != c.fbt {
			t.Fatalf("%s FBT rule present = %v, want %v", c.period.Format("2006-01"), cfg.FBT != nil, c.fbt)
		}
		if c.fbt && (!cfg.FBT.MarketRate.Equal(decimal.RequireFromString(c.mkt)) || !cfg.FBT.TaxRate.Equal(decimal.RequireFromString("0.30"))) {
			t.Errorf("%s FBT market %s tax %s, want %s and 0.30", c.period.Format("2006-01"), cfg.FBT.MarketRate, cfg.FBT.TaxRate, c.mkt)
		}
		// PAYE stays on the enacted bands: the first band still taxes at 10%.
		if r := cfg.Income.Bands[0].Rate; !r.Equal(decimal.RequireFromString("0.1")) {
			t.Errorf("%s first PAYE band rate %s, want 0.1 (the bill bands must stay inactive)", c.period.Format("2006-01"), r)
		}
	}
}
