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

func TestGetRealIP(t *testing.T) {
	cases := []struct {
		name       string
		xff        string
		xRealIP    string
		remoteAddr string
		want       string
	}{
		{"x-forwarded-for first hop", "203.0.113.1, 10.0.0.1", "", "10.0.0.5:1234", "203.0.113.1"},
		{"x-real-ip", "", "203.0.113.2", "10.0.0.5:1234", "203.0.113.2"},
		{"remote addr strips port", "", "", "203.0.113.3:5678", "203.0.113.3"},
		{"xff precedence over real-ip", "203.0.113.4", "203.0.113.9", "10.0.0.5:1", "203.0.113.4"},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := httptest.NewRequest(http.MethodGet, "/", nil)
			if tc.xff != "" {
				r.Header.Set("X-Forwarded-For", tc.xff)
			}
			if tc.xRealIP != "" {
				r.Header.Set("X-Real-IP", tc.xRealIP)
			}
			r.RemoteAddr = tc.remoteAddr
			if got := getRealIP(r); got != tc.want {
				t.Errorf("getRealIP() = %q, want %q", got, tc.want)
			}
		})
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

// TestMiddlewareFailsOpenWithoutRedis verifies that when enabled but Redis is unavailable
// (nil client), requests are allowed (fail open) rather than blocked.
func TestMiddlewareFailsOpenWithoutRedis(t *testing.T) {
	rl := NewRateLimiter(nil, RateLimitConfig{Enabled: true, KeyPrefix: "rl:test:"}, zap.NewNop())
	allowed := 0
	h := rl.IPRateLimiter(1, time.Minute)(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		allowed++
		w.WriteHeader(http.StatusOK)
	}))
	for i := 0; i < 5; i++ {
		rec := httptest.NewRecorder()
		h.ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/", nil))
		if rec.Code != http.StatusOK {
			t.Fatalf("request %d: got %d, want 200 (fail open)", i, rec.Code)
		}
	}
	if allowed != 5 {
		t.Errorf("fail-open should allow all 5 requests, got %d", allowed)
	}
}
