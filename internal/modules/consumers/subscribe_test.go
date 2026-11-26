package consumers

import (
	"testing"
	"time"
)

// TestRetryAfterBacksOffThenGivesUp: a failed event waits longer after each attempt, never more
// than the cap, never less than three quarters of the step, and is given up after the last one.
func TestRetryAfterBacksOffThenGivesUp(t *testing.T) {
	none := func(time.Duration) time.Duration { return 0 }
	full := func(max time.Duration) time.Duration { return max }
	want := []time.Duration{5 * time.Second, 10 * time.Second, 20 * time.Second, 40 * time.Second}
	for i, w := range want {
		giveUp, d := retryAfter(uint64(i+1), none)
		if giveUp || d != w {
			t.Fatalf("attempt %d: give up %v, delay %v, want %v", i+1, giveUp, d, w)
		}
		if _, d := retryAfter(uint64(i+1), full); d != w-w/4 {
			t.Fatalf("attempt %d with jitter: %v", i+1, d)
		}
	}
	for _, n := range []uint64{maxDeliver, maxDeliver + 1, 1000} {
		if giveUp, _ := retryAfter(n, none); !giveUp {
			t.Fatalf("attempt %d must give up", n)
		}
	}
	// The cap holds for any step.
	for n := uint64(1); n < maxDeliver; n++ {
		if _, d := retryAfter(n, none); d > retryCap {
			t.Fatalf("attempt %d: %v over the cap", n, d)
		}
	}
	for i := 0; i < 100; i++ {
		if j := randomJitter(time.Second); j < 0 || j >= time.Second {
			t.Fatalf("jitter %v", j)
		}
	}
}
