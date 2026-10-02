package middleware

import (
	"net/http"
	"net/http/httptest"
	"testing"
	"time"

	"go.uber.org/zap"
)

func TestWithBurst(t *testing.T) {
	cases := []struct {
		mult  float64
		limit int
		want  int
	}{
		{0, 100, 100},   // no burst configured
		{1, 100, 100},   // 1x = no change
		{1.5, 100, 150}, // 50% headroom
		{1.5, 0, 0},
		{0.5, 100, 100}, // never below base limit
	}
	for _, tc := range cases {
		c := RateLimitConfig{BurstMultiplier: tc.mult}
		if got := c.WithBurst(tc.limit); got != tc.want {
			t.Errorf("WithBurst(mult=%v, limit=%d) = %d, want %d", tc.mult, tc.limit, got, tc.want)
		}
	}
}

// TestMiddlewareDisabledPassesThrough verifies the limiter is a no-op (and sets no headers)
// when disabled, so it can be safely toggled off via RATE_LIMIT_ENABLED.
func TestMiddlewareDisabledPassesThrough(t *testing.T) {
	rl := NewRateLimiter(nil, RateLimitConfig{Enabled: false}, zap.NewNop())
	called := false
	h := rl.IPRateLimiter(1, time.Minute)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		called = true
		w.WriteHeader(http.StatusOK)
	}))
	rec := httptest.NewRecorder()
	h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/", nil))
	if !called {
		t.Fatal("disabled limiter should call next handler")
	}
	if rec.Header().Get("X-RateLimit-Limit") != "" {
		t.Errorf("disabled limiter should not set rate-limit headers")
	}
}

// TestMiddlewareFallsBackWithoutRedis verifies that when enabled but Redis is unavailable (nil
// client) the limiter neither blocks everyone nor lets everything through: the per-pod fallback
// bucket admits this pod's share of the limit and then answers 429.
func TestMiddlewareFallsBackWithoutRedis(t *testing.T) {
	rl := NewRateLimiter(nil, RateLimitConfig{Enabled: true}, zap.NewNop())
	allowed, limited := 0, 0
	h := rl.IPRateLimiter(10, time.Minute)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusOK)
	}))
	for i := 0; i < 20; i++ {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/", nil))
		switch rec.Code {
		case http.StatusOK:
			allowed++
		case http.StatusTooManyRequests:
			limited++
		default:
			t.Fatalf("request %d: unexpected status %d", i, rec.Code)
		}
	}
	if allowed == 0 || allowed > 10 || limited == 0 {
		t.Errorf("fallback admitted %d and limited %d of 20; want some of each, at most 10 admitted", allowed, limited)
	}
}
