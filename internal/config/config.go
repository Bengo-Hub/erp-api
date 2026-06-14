package config

import (
	"fmt"
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
