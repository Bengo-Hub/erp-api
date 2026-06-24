package middleware

import (
	"context"
	"fmt"
	"net/http"
	"strconv"
	"strings"
	"time"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	"github.com/redis/go-redis/v9"
	"go.uber.org/zap"
)

// RateLimiter provides distributed rate limiting backed by Redis. It uses a sliding-window
// algorithm (ZREMRANGEBYSCORE + ZCARD + ZADD) so there is no fixed-window cliff at the
// boundary, and it works correctly across replicas because all state lives in Redis. The
// design is ported from ordering-backend's security.RateLimiter — the best-in-class model in
// the monorepo — adapted to erp's tenant-from-JWT-claims convention.
//
// It FAILS OPEN: any Redis error allows the request, so a Redis outage degrades to "no rate
// limiting" rather than a hard outage.
type RateLimiter struct {
	redis  *redis.Client
	logger *zap.Logger
	config RateLimitConfig
}

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

	// KeyPrefix namespaces the Redis keys so erp does not collide with other services that
	// share the Redis instance.
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

// NewRateLimiter creates a Redis-backed rate limiter.
func NewRateLimiter(redisClient *redis.Client, config RateLimitConfig, logger *zap.Logger) *RateLimiter {
	return &RateLimiter{
		redis:  redisClient,
		logger: logger.Named("rate_limiter"),
		config: config,
	}
}

// Config returns the limiter's resolved configuration (used by main.go to derive limits).
func (rl *RateLimiter) Config() RateLimitConfig { return rl.config }

// RateLimitResult is the outcome of a single Check.
type RateLimitResult struct {
	Allowed   bool
	Remaining int
	ResetAt   time.Time
	RetryAt   *time.Time
}

// Check performs a sliding-window rate-limit check for key against limit over window.
func (rl *RateLimiter) Check(ctx context.Context, key string, limit int, window time.Duration) (*RateLimitResult, error) {
	if !rl.config.Enabled || rl.redis == nil || limit <= 0 {
		return &RateLimitResult{Allowed: true, Remaining: limit}, nil
	}

	// Fail fast on a slow Redis so request latency is never held hostage by the limiter.
	redisCtx, cancel := context.WithTimeout(ctx, 200*time.Millisecond)
	defer cancel()

	now := time.Now()
	windowStart := now.Add(-window)
	redisKey := rl.config.KeyPrefix + key

	pipe := rl.redis.Pipeline()
	pipe.ZRemRangeByScore(redisCtx, redisKey, "0", strconv.FormatInt(windowStart.UnixMilli(), 10))
	countCmd := pipe.ZCard(redisCtx, redisKey)
	if _, err := pipe.Exec(redisCtx); err != nil && err != redis.Nil {
		rl.logger.Warn("rate limiter pipeline error (failing open)", zap.Error(err), zap.String("key", key))
		return &RateLimitResult{Allowed: true, Remaining: limit}, nil
	}

	count := int(countCmd.Val())
	remaining := limit - count
	if remaining <= 0 {
		result := &RateLimitResult{Allowed: false, Remaining: 0, ResetAt: now.Add(window)}
		if oldest, err := rl.redis.ZRangeWithScores(redisCtx, redisKey, 0, 0).Result(); err == nil && len(oldest) > 0 {
			retryAt := time.UnixMilli(int64(oldest[0].Score)).Add(window)
			result.RetryAt = &retryAt
		}
		return result, nil
	}

	// Record this request in the window. Member must be unique to avoid ZADD overwrite.
	if err := rl.redis.ZAdd(redisCtx, redisKey, redis.Z{
		Score:  float64(now.UnixMilli()),
		Member: fmt.Sprintf("%d", now.UnixNano()),
	}).Err(); err != nil {
		rl.logger.Warn("failed to record rate-limit entry", zap.Error(err), zap.String("key", key))
	}
	rl.redis.Expire(redisCtx, redisKey, window+time.Minute)

	return &RateLimitResult{Allowed: true, Remaining: remaining - 1, ResetAt: now.Add(window)}, nil
}

// Middleware enforces rate limiting using keyFunc to derive the per-caller bucket.
func (rl *RateLimiter) Middleware(keyFunc func(r *http.Request) string, limit int, window time.Duration) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			if !rl.config.Enabled {
				next.ServeHTTP(w, r)
				return
			}
			result, err := rl.Check(r.Context(), keyFunc(r), limit, window)
			if err != nil || result == nil {
				next.ServeHTTP(w, r) // fail open
				return
			}

			w.Header().Set("X-RateLimit-Limit", strconv.Itoa(limit))
			w.Header().Set("X-RateLimit-Remaining", strconv.Itoa(result.Remaining))
			w.Header().Set("X-RateLimit-Reset", strconv.FormatInt(result.ResetAt.Unix(), 10))

			if !result.Allowed {
				if result.RetryAt != nil {
					retry := int64(time.Until(*result.RetryAt).Seconds())
					if retry < 1 {
						retry = 1
					}
					w.Header().Set("Retry-After", strconv.FormatInt(retry, 10))
				}
				w.Header().Set("Content-Type", "application/json")
				w.WriteHeader(http.StatusTooManyRequests)
				_, _ = w.Write([]byte(`{"error":"too many requests, please try again later","code":"rate_limited"}`))
				return
			}
			next.ServeHTTP(w, r)
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
