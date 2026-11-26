package payrollsettings

import (
	"context"
	"errors"
	"testing"
	"time"

	"go.uber.org/zap"

	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
)

// A failed pull gives up for the period without touching the formulas, and the pull is bounded
// by its timeout.
func TestTreasuryRatesCronGivesUp(t *testing.T) {
	calls := 0
	c := NewTreasuryRatesCron(nil, func(ctx context.Context) ([]treasury.StatutoryRate, error) {
		calls++
		if _, ok := ctx.Deadline(); !ok {
			t.Error("the pull runs without a deadline")
		}
		return nil, errors.New("treasury 503 after 3 attempts")
	}, zap.NewNop(), 0)
	c.timeout = time.Second
	if n, err := c.RunOnce(context.Background()); err == nil || n != 0 || calls != 1 {
		t.Errorf("failed pull: applied %d err %v calls %d", n, err, calls)
	}

	// Only the replica that claims the period runs it.
	ran := 0
	c.list = func(context.Context) ([]treasury.StatutoryRate, error) { ran++; return nil, errors.New("x") }
	c.claim = func(context.Context, string, time.Duration) bool { return false }
	ctx, cancel := context.WithCancel(context.Background())
	c.Start(ctx)
	cancel()
	if ran != 0 {
		t.Error("ran without claiming the period")
	}
}
