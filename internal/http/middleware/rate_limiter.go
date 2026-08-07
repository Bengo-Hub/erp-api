package middleware

import (
	"fmt"
	"net/http"
	"strings"
	"time"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	sharedratelimit "github.com/Bengo-Hub/shared-ratelimit"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

// RateLimitConfig configures rate-limiting behavior. Populated from the environment via
// envconfig (embedded in config.Config as the RateLimit field).
type RateLimitConfig struct {
	// Default per-window limits applied to the general authenticated surface.
	RequestsPerMinute int `envconfig:"RATE_LIMIT_REQUESTS_PER_MINUTE" default:"100"`
	RequestsPerHour   int `envconfig:"RATE_LIMIT_REQUESTS_PER_HOUR" default:"2500"`

	// Stricter per-window limits for sensitive endpoints (auth/refresh and money paths such as
	// payroll process/disburse and backups).
	AuthRequestsPerMinute    int `envconfig:"RATE_LIMIT_AUTH_PER_MINUTE" default:"10"`
	PaymentRequestsPerMinute int `envconfig:"RATE_LIMIT_PAYMENT_PER_MINUTE" default:"20"`

	// BurstMultiplier scales a limit to absorb short spikes (e.g. 1.5 = allow 150% briefly).
	BurstMultiplier float64 `envconfig:"RATE_LIMIT_BURST_MULTIPLIER" default:"1.5"`

	// KeyPrefix is retained for envconfig/env-var compatibility (RATE_LIMIT_KEY_PREFIX is set
	// to "rl:erp:" in prod config) but is no longer read directly — shared-ratelimit.Limiter
	// derives the identical prefix from its servicePrefix argument ("erp" -> "rl:erp:").
	KeyPrefix string `envconfig:"RATE_LIMIT_KEY_PREFIX" default:"rl:erp:"`

	// Enabled toggles enforcement. When false, every limiter is a no-op pass-through.
	Enabled bool `envconfig:"RATE_LIMIT_ENABLED" default:"true"`
}

// WithBurst returns limit scaled by BurstMultiplier (rounded down), never below limit.
func (c RateLimitConfig) WithBurst(limit int) int {
	if c.BurstMultiplier <= 1 {
		return limit
	}
	scaled := int(float64(limit) * c.BurstMultiplier)
	if scaled < limit {
		return limit
	}
	return scaled
}

// RateLimiter wraps github.com/Bengo-Hub/shared-ratelimit's Limiter — the same Redis
// sliding-window primitive (ZREMRANGEBYSCORE + ZCARD + ZADD, fail-open on any Redis error)
// treasury-api uses, extracted from what used to be erp's own hand-rolled copy of the same
// algorithm (ported from ordering-backend's security.RateLimiter) — with erp's
// tenant/IP/endpoint key strategies and its RATE_LIMIT_ENABLED killswitch layered on top.
type RateLimiter struct {
	limiter *sharedratelimit.Limiter
	config  RateLimitConfig
}

// NewRateLimiter creates a Redis-backed rate limiter.
func NewRateLimiter(redisClient *redis.Client, config RateLimitConfig, logger *zap.Logger) *RateLimiter {
	return &RateLimiter{
		limiter: sharedratelimit.NewLimiter(redisClient, logger, "erp"),
		config:  config,
	}
}

// Config returns the limiter's resolved configuration (used by main.go to derive limits).
func (rl *RateLimiter) Config() RateLimitConfig { return rl.config }

// Middleware enforces rate limiting using keyFunc to derive the per-caller bucket. A no-op
// pass-through (no headers set) when RateLimitConfig.Enabled is false.
func (rl *RateLimiter) Middleware(keyFunc func(r *http.Request) string, limit int, window time.Duration) func(http.Handler) http.Handler {
	limited := rl.limiter.Middleware(keyFunc, limit, window)
	return func(next http.Handler) http.Handler {
		wrapped := limited(next)
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !rl.config.Enabled {
				next.ServeHTTP(w, r)
				return
			}
			wrapped.ServeHTTP(w, r)
		})
	}
}

// TenantRateLimiter rate-limits per tenant — the fair multi-tenant default so one busy tenant
// cannot starve others. It reads the tenant from the validated JWT claims (set by RequireAuth),
// falling back to the X-Tenant-ID header and finally the caller IP for unauthenticated paths.
func (rl *RateLimiter) TenantRateLimiter(limit int, window time.Duration) func(http.Handler) http.Handler {
	return rl.Middleware(func(r *http.Request) string {
		if claims, ok := authclient.ClaimsFromContext(r.Context()); ok && claims != nil {
			if t, err := claims.TenantUUID(); err == nil && t != nil {
				return "tenant:" + t.String()
			}
		}
		if t := r.Header.Get("X-Tenant-ID"); t != "" {
			return "tenant:" + t
		}
		return "ip:" + getRealIP(r)
	}, limit, window)
}

// IPRateLimiter rate-limits per client IP.
func (rl *RateLimiter) IPRateLimiter(limit int, window time.Duration) func(http.Handler) http.Handler {
	return rl.Middleware(func(r *http.Request) string {
		return "ip:" + getRealIP(r)
	}, limit, window)
}

// EndpointRateLimiter rate-limits per (endpoint, IP) — used to harden sensitive routes such as
// payroll process/disburse and bulk import beyond the per-tenant budget.
func (rl *RateLimiter) EndpointRateLimiter(endpoint string, limit int, window time.Duration) func(http.Handler) http.Handler {
	return rl.Middleware(func(r *http.Request) string {
		return fmt.Sprintf("endpoint:%s:ip:%s", endpoint, getRealIP(r))
	}, limit, window)
}

// getRealIP extracts the client IP, honoring the proxy headers set by the ingress.
func getRealIP(r *http.Request) string {
	if xff := r.Header.Get("X-Forwarded-For"); xff != "" {
		if i := strings.IndexByte(xff, ','); i >= 0 {
			return strings.TrimSpace(xff[:i])
		}
		return strings.TrimSpace(xff)
	}
	if xri := r.Header.Get("X-Real-IP"); xri != "" {
		return xri
	}
	ip := r.RemoteAddr
	if i := strings.LastIndexByte(ip, ':'); i >= 0 {
		return ip[:i]
	}
	return ip
}
