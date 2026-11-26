package payrollsettings

import (
	"context"
	"time"

	sharedcache "github.com/Bengo-Hub/cache"
	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

// RatesLister reads treasury's in-force statutory rates.
type RatesLister func(ctx context.Context) ([]treasury.StatutoryRate, error)

// TreasuryRatesCron pulls treasury's statutory rates once a day (on one replica) and applies the
// newer approved changes to the platform formulas, so a change reaches payroll without a deploy.
type TreasuryRatesCron struct {
	svc      *Service
	list     RatesLister
	log      *zap.Logger
	interval time.Duration
	timeout  time.Duration
	// claim decides whether this replica runs the period (replaced in tests).
	claim func(ctx context.Context, key string, ttl time.Duration) bool
}

// NewTreasuryRatesCron builds the daily pull; interval <= 0 means 24h.
func NewTreasuryRatesCron(svc *Service, list RatesLister, log *zap.Logger, interval time.Duration) *TreasuryRatesCron {
	if interval <= 0 {
		interval = 24 * time.Hour
	}
	return &TreasuryRatesCron{svc: svc, list: list, log: log.Named("payrollsettings.treasury_rates_cron"),
		interval: interval, timeout: 2 * time.Minute, claim: sharedcache.ClaimPeriod}
}

// Start ticks hourly until ctx ends; the first replica to claim each period runs the pull.
func (c *TreasuryRatesCron) Start(ctx context.Context) {
	go func() {
		ticker := time.NewTicker(time.Hour)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-ticker.C:
				if c.claim(ctx, "erp:treasury-rates-pull", c.interval) {
					c.RunOnce(ctx)
				}
			}
		}
	}()
}

// RunOnce pulls and applies the rates within the timeout. A failed pull is logged and waits for
// the next period (the list call itself retries a few times with backoff); nothing is changed.
func (c *TreasuryRatesCron) RunOnce(ctx context.Context) (applied int, err error) {
	ctx, cancel := context.WithTimeout(ctx, c.timeout)
	defer cancel()
	rates, err := c.list(ctx)
	if err != nil {
		c.log.Error("statutory rates pull failed; next try next period", zap.Error(err))
		return 0, err
	}
	res, err := c.svc.SyncTreasuryRates(ctx, rates)
	if err != nil {
		c.log.Error("statutory rates sync failed", zap.Error(err))
		return 0, err
	}
	for _, r := range res {
		c.log.Info("treasury statutory rates", zap.String("type", r.Type), zap.String("category", r.Category),
			zap.String("action", r.Action), zap.Time("effective_from", r.EffectiveFrom))
		if r.Action == "applied" {
			applied++
		}
	}
	return applied, nil
}
