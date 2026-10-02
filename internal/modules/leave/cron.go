package leave

import (
	"context"
	sharedcache "github.com/Bengo-Hub/cache"
	"time"

	"go.uber.org/zap"
)

// AccrualCron runs the leave-accrual job on a fixed interval (Go replacement for the
// Celery/management-command accrue_leave). It is idempotent, so a coarse daily tick is
// safe — each run refreshes the current year's balances across all tenants. A k8s CronJob
// invoking cmd/seed-style accrual is the production option; this in-process goroutine is the
// default so a single replica keeps balances fresh without external scheduling.
type AccrualCron struct {
	svc      *Service
	log      *zap.Logger
	interval time.Duration
}

// NewAccrualCron builds the cron. interval <= 0 defaults to 24h.
func NewAccrualCron(svc *Service, log *zap.Logger, interval time.Duration) *AccrualCron {
	if interval <= 0 {
		interval = 24 * time.Hour
	}
	return &AccrualCron{svc: svc, log: log.Named("leave.accrual_cron"), interval: interval}
}

// Start launches the cron goroutine; it stops when ctx is cancelled. Runs once shortly
// after start, then every interval.
func (c *AccrualCron) Start(ctx context.Context) {
	go func() {
		// Small initial delay so startup isn't blocked by the first run.
		timer := time.NewTimer(30 * time.Second)
		defer timer.Stop()
		ticker := time.NewTicker(c.interval)
		defer ticker.Stop()
		for {
			select {
			case <-ctx.Done():
				return
			case <-timer.C:
				c.runOnce(ctx)
			case <-ticker.C:
				c.runOnce(ctx)
			}
		}
	}()
	c.log.Info("leave accrual cron started", zap.Duration("interval", c.interval))
}

func (c *AccrualCron) runOnce(ctx context.Context) {
	// Runs on every replica's ticker; only the first replica in each period does the work.
	if !sharedcache.ClaimPeriod(ctx, "erp:leave-accrual", c.interval) {
		return
	}
	year := time.Now().UTC().Year()
	n, err := c.svc.AccrueAllTenants(ctx, year)
	if err != nil {
		c.log.Error("leave accrual run failed", zap.Int("year", year), zap.Error(err))
		return
	}
	c.log.Info("leave accrual run complete", zap.Int("year", year), zap.Int("rows", n))
}
