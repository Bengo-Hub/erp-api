package config

import (
	"fmt"
	"net/url"
	"time"

	"github.com/joho/godotenv"
	"github.com/kelseyhightower/envconfig"
)

const namespace = ""

// Config aggregates runtime configuration for the erp service.
// Mirrors the Django env vars documented in docs/architecture.md §5.
type Config struct {
	App      AppConfig
	HTTP     HTTPConfig
	Postgres PostgresConfig
	Redis    RedisConfig
	Events   EventsConfig
	Auth     AuthConfig
	Services ServicesConfig
	Media    MediaConfig
}

type AppConfig struct {
	Name    string `envconfig:"APP_NAME" default:"erp-api"`
	Env     string `envconfig:"APP_ENV" default:"development"`
	Region  string `envconfig:"APP_REGION" default:"africa-east-1"`
	Version string `envconfig:"APP_VERSION" default:"0.1.0"`
}

type HTTPConfig struct {
	Host         string        `envconfig:"HTTP_HOST" default:"0.0.0.0"`
	Port         int           `envconfig:"HTTP_PORT" default:"4000"`
	ReadTimeout  time.Duration `envconfig:"HTTP_READ_TIMEOUT" default:"20s"`
	WriteTimeout time.Duration `envconfig:"HTTP_WRITE_TIMEOUT" default:"20s"`
	IdleTimeout  time.Duration `envconfig:"HTTP_IDLE_TIMEOUT" default:"90s"`
	TLSCertFile  string        `envconfig:"TLS_CERT_FILE"`
	TLSKeyFile   string        `envconfig:"TLS_KEY_FILE"`
	// AllowedOrigins is an explicit allow-list; never use a credentialed wildcard (fixes gaps §1.3).
	AllowedOrigins []string `envconfig:"HTTP_ALLOWED_ORIGINS" default:"https://erp.codevertexitsolutions.com,https://accounts.codevertexitsolutions.com,http://localhost:3000"`
}

type PostgresConfig struct {
	URL                      string        `envconfig:"POSTGRES_URL" default:"postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable"`
	MaxOpenConns             int           `envconfig:"POSTGRES_MAX_OPEN_CONNS" default:"5"`
	MaxIdleConns             int           `envconfig:"POSTGRES_MAX_IDLE_CONNS" default:"3"`
	ConnMaxLifetime          time.Duration `envconfig:"POSTGRES_CONN_MAX_LIFETIME" default:"5m"`
	StatementTimeout         time.Duration `envconfig:"POSTGRES_STATEMENT_TIMEOUT" default:"30s"`
	IdleInTransactionTimeout time.Duration `envconfig:"POSTGRES_IDLE_IN_TRANSACTION_TIMEOUT" default:"60s"`
	// RunMigrations applies versioned migrations on boot. Keep false in prod; the entrypoint
	// runs cmd/migrate before the server starts.
	RunMigrations bool `envconfig:"POSTGRES_RUN_MIGRATIONS" default:"false"`
	// Schema is the Postgres schema the Go ERP lives in. It is "erp" (NOT public) so the new
	// Ent tables are isolated from the legacy Django tables that still occupy the public schema
	// of the SAME bengo_erp database during/after cutover (16 table names collide). See
	// docs/data-migration-runbook.md.
	Schema string `envconfig:"DB_SCHEMA" default:"erp"`

	// Direct-connection components. When Host is set (DB_HOST), the DSN is built from these
	// instead of URL. This is REQUIRED in prod: POSTGRES_URL points at pgbouncer (transaction
	// pooling), which resets the per-session search_path (breaking the erp schema) and breaks
	// pgx prepared statements. The Go ERP therefore connects DIRECTLY to postgresql (small pool),
	// pulling DB_USER/DB_PASSWORD/DB_NAME from the k8s secret and overriding DB_HOST to the
	// postgresql service. See docs/data-migration-runbook.md.
	Host     string `envconfig:"DB_HOST"`
	Port     string `envconfig:"DB_PORT" default:"5432"`
	User     string `envconfig:"DB_USER"`
	Password string `envconfig:"DB_PASSWORD"`
	Name     string `envconfig:"DB_NAME"`
	SSLMode  string `envconfig:"DB_SSLMODE" default:"disable"`
}

// DSN returns the Postgres connection string with search_path pinned to the configured schema
// (erp). When DB_HOST is set it builds a DIRECT postgresql DSN from the component vars (bypassing
// pgbouncer — needed for persistent search_path + prepared statements); otherwise it falls back
// to POSTGRES_URL.
func (c PostgresConfig) DSN() string {
	base := c.URL
	if c.Host != "" {
		u := url.URL{
			Scheme: "postgres",
			User:   url.UserPassword(c.User, c.Password),
			Host:   c.Host + ":" + c.Port,
			Path:   "/" + c.Name,
		}
		q := url.Values{}
		q.Set("sslmode", c.SSLMode)
		u.RawQuery = q.Encode()
		base = u.String()
	}
	return EnsureSearchPath(base, c.Schema)
}

// EnsureSearchPath returns dsn with its search_path query parameter set to schema.
// pgx (used by both pgxpool and the database/sql stdlib driver) sends unknown URL query
// params as Postgres runtime parameters, so search_path is honored on every connection.
// If dsn can't be parsed, it's returned unchanged.
func EnsureSearchPath(dsn, schema string) string {
	if schema == "" {
		return dsn
	}
	u, err := url.Parse(dsn)
	if err != nil {
		return dsn
	}
	q := u.Query()
	q.Set("search_path", schema)
	u.RawQuery = q.Encode()
	return u.String()
}

type RedisConfig struct {
	Addr        string        `envconfig:"REDIS_ADDR" default:"localhost:6379"`
	Username    string        `envconfig:"REDIS_USERNAME"`
	Password    string        `envconfig:"REDIS_PASSWORD"`
	DB          int           `envconfig:"REDIS_DB" default:"0"`
	TLSRequired bool          `envconfig:"REDIS_TLS_REQUIRED" default:"false"`
	DialTimeout time.Duration `envconfig:"REDIS_DIAL_TIMEOUT" default:"5s"`
}

type EventsConfig struct {
	Enabled          bool          `envconfig:"EVENTS_ENABLED" default:"true"`
	Bus              string        `envconfig:"EVENT_BUS" default:"nats"`
	NATSURL          string        `envconfig:"EVENTS_NATS_URL" default:"nats://localhost:4222"`
	StreamName       string        `envconfig:"NATS_STREAM" default:"erp"`
	SourceService    string        `envconfig:"EVENTS_SOURCE_SERVICE" default:"erp"`
	DeliverGroup     string        `envconfig:"NATS_DELIVER_GROUP" default:"erp-workers"`
	OutboxEnabled    bool          `envconfig:"OUTBOX_ENABLED" default:"true"`
	OutboxBatchSize  int           `envconfig:"OUTBOX_BATCH_SIZE" default:"100"`
	OutboxPollPeriod time.Duration `envconfig:"OUTBOX_POLL_PERIOD" default:"5s"`
	MaxAttempts      int           `envconfig:"EVENTS_MAX_ATTEMPTS" default:"10"`
	// LeaveAccrualInterval is the period of the in-process leave-accrual cron
	// (Go replacement for the accrue_leave management command). Idempotent, so a daily
	// tick is safe. Disable via a very large value when running accrual as a k8s CronJob.
	LeaveAccrualInterval time.Duration `envconfig:"LEAVE_ACCRUAL_INTERVAL" default:"24h"`
	// FXFetchInterval is the period of the in-process FX-rate fetch cron (Go replacement for
	// the Celery Beat fetch_exchange_rates task). Idempotent per (base,quote,date).
	FXFetchInterval time.Duration `envconfig:"FX_FETCH_INTERVAL" default:"24h"`
}

type AuthConfig struct {
	ServiceURL          string        `envconfig:"AUTH_SERVICE_URL" default:"https://sso.codevertexitsolutions.com"`
	Issuer              string        `envconfig:"AUTH_ISSUER" default:"https://sso.codevertexitsolutions.com"`
	Audience            string        `envconfig:"AUTH_AUDIENCE" default:"codevertex"`
	JWKSUrl             string        `envconfig:"AUTH_JWKS_URL" default:"https://sso.codevertexitsolutions.com/api/v1/.well-known/jwks.json"`
	JWKSCacheTTL        time.Duration `envconfig:"AUTH_JWKS_CACHE_TTL" default:"3600s"`
	JWKSRefreshInterval time.Duration `envconfig:"AUTH_JWKS_REFRESH_INTERVAL" default:"300s"`
	EnableAPIKeyAuth    bool          `envconfig:"AUTH_ENABLE_API_KEY_AUTH" default:"true"`
	// APIKey is the shared INTERNAL_SERVICE_KEY used for S2S X-API-Key auth.
	APIKey string `envconfig:"INTERNAL_SERVICE_KEY" default:""`
}

type ServicesConfig struct {
	TreasuryURL      string `envconfig:"TREASURY_SERVICE_URL" default:"https://booksapi.codevertexitsolutions.com"`
	NotificationsURL string `envconfig:"NOTIFICATIONS_SERVICE_URL" default:""`
}

type MediaConfig struct {
	Root    string `envconfig:"MEDIA_ROOT" default:"./media"`
	URLBase string `envconfig:"MEDIA_URL_BASE" default:""`
}

// Load gathers configuration from environment variables and an optional .env file.
func Load() (*Config, error) {
	_ = godotenv.Load()

	var cfg Config
	if err := envconfig.Process(namespace, &cfg); err != nil {
		return nil, fmt.Errorf("config: failed to load environment variables: %w", err)
	}

	return &cfg, nil
}
