package fx

import (
	"context"
	"time"

	"go.uber.org/zap"
)

// Cron runs the FX-fetch job on a fixed interval (Go replacement for the Celery Beat
// fetch_exchange_rates daily task). Idempotent per (base,quote,date) so a coarse tick is safe.
type Cron struct {
	svc      *Service
	log      *zap.Logger
	interval time.Duration
}

// NewCron builds the FX cron. interval <= 0 defaults to 24h.
func NewCron(svc *Service, log *zap.Logger, interval time.Duration) *Cron {
	if interval <= 0 {
		interval = 24 * time.Hour
	}
	return &Cron{svc: svc, log: log.Named("fx.cron"), interval: interval}
}

// Start launches the cron goroutine; it stops when ctx is cancelled.
func (c *Cron) Start(ctx context.Context) {
	go func() {
		timer := time.NewTimer(45 * time.Second)
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
	c.log.Info("fx cron started", zap.Duration("interval", c.interval))
}

func (c *Cron) runOnce(ctx context.Context) {
	n, err := c.svc.FetchAllActive(ctx)
	if err != nil {
		c.log.Error("fx fetch run failed", zap.Error(err))
		return
	}
	c.log.Info("fx fetch run complete", zap.Int("rates", n))
}
