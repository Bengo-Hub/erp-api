package attendance

import (
	"context"
	"errors"
	"fmt"
	"time"

	sharedcache "github.com/Bengo-Hub/cache"
	"github.com/google/uuid"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

// Cron runs the attendance background work on every replica's ticker; the shared cache leases
// make sure each unit of work runs once fleet-wide: rotation advance once a day, auto-absent
// once per tenant and work day, and the punch processor sweep under an exclusive lease.
type Cron struct {
	svc      *Service
	rdb      redis.UniversalClient
	log      *zap.Logger
	interval time.Duration
}

// NewCron builds the attendance cron. interval <= 0 defaults to 15 minutes; rdb may be nil
// (single instance, local development).
func NewCron(svc *Service, rdb redis.UniversalClient, log *zap.Logger, interval time.Duration) *Cron {
	if interval <= 0 {
		interval = 15 * time.Minute
	}
	return &Cron{svc: svc, rdb: rdb, log: log.Named("attendance.cron"), interval: interval}
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
				c.tick(ctx)
			case <-ticker.C:
				c.tick(ctx)
			}
		}
	}()
	c.log.Info("attendance cron started", zap.Duration("interval", c.interval))
}

func (c *Cron) tick(ctx context.Context) {
	now := time.Now()
	if sharedcache.ClaimPeriod(ctx, "erp:attendance:rotations", 24*time.Hour) {
		if n, err := c.svc.AdvanceRotations(ctx, now); err != nil {
			c.log.Error("rotation advance failed", zap.Error(err))
		} else if n > 0 {
			c.log.Info("rotations advanced", zap.Int("count", n))
		}
	}
	c.runOnce(ctx, "erp:attendance:punch-sweep", c.interval, func(ctx context.Context) error {
		_, err := c.svc.ProcessPendingPunches(ctx, uuid.Nil)
		return err
	})
	c.autoAbsent(ctx, now)
}

// autoAbsent closes the current work day for every tenant that switched auto-absent on.
func (c *Cron) autoAbsent(ctx context.Context, now time.Time) {
	tenants, err := c.svc.tenantsWithSettings(ctx)
	if err != nil {
		c.log.Error("auto-absent settings load failed", zap.Error(err))
		return
	}
	for tenantID, st := range tenants {
		if !st.AutoAbsentEnabled {
			continue
		}
		zones, err := c.svc.loadZones(ctx, tenantID)
		if err != nil {
			c.log.Warn("auto-absent zone load failed", zap.String("tenant", tenantID.String()), zap.Error(err))
			continue
		}
		day, ok := autoAbsentDay(now, zones.For(), st.AutoAbsentTime)
		if !ok {
			continue
		}
		key := fmt.Sprintf("erp:attendance:auto-absent:%s:%s", tenantID, day.Format("20060102"))
		tid, st := tenantID, st
		c.runOnce(ctx, key, 48*time.Hour, func(ctx context.Context) error {
			n, err := c.svc.MarkAbsent(ctx, tid, day, st)
			if err == nil && n > 0 {
				c.log.Info("auto-absent marked", zap.String("tenant", tid.String()),
					zap.String("day", day.Format("2006-01-02")), zap.Int64("rows", n))
			}
			return err
		})
	}
}

// runOnce runs fn under a fleet-wide RunOnce lease; without Redis it just runs fn.
func (c *Cron) runOnce(ctx context.Context, key string, hold time.Duration, fn func(context.Context) error) {
	var err error
	if c.rdb == nil {
		err = fn(ctx)
	} else {
		_, err = sharedcache.RunOnce(ctx, c.rdb, c.log, key, hold, fn)
	}
	if err != nil && !errors.Is(err, sharedcache.ErrLockUnavailable) {
		c.log.Error("attendance job failed", zap.String("key", key), zap.Error(err))
	}
}
