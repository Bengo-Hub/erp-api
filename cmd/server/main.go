// Command server is the erp-api HTTP entrypoint. It wires the Sprint 1 foundation:
// config, Ent ORM (Postgres), Redis cache, NATS + transactional outbox, SSO/JWKS auth,
// tenant/outlet context, the tenant-sync consumers, and the public + authenticated routes.
//
// This is the Go replacement for the Django ProcureProKEAPI WSGI app (docs/revamp-plan.md).
package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"
	_ "github.com/jackc/pgx/v5/stdlib" // register the "pgx" database/sql driver
	"github.com/nats-io/nats.go"
	"go.uber.org/zap"

	authclient "github.com/Bengo-Hub/shared-auth-client"
	eventslib "github.com/Bengo-Hub/shared-events"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/http/handlers"
	mw "github.com/Bengo-Hub/erp-api/internal/http/middleware"
	"github.com/Bengo-Hub/erp-api/internal/modules/consumers"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
	"github.com/Bengo-Hub/erp-api/internal/platform/cache"
	"github.com/Bengo-Hub/erp-api/internal/platform/database"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
	"github.com/Bengo-Hub/erp-api/internal/services/usersync"
	"github.com/Bengo-Hub/erp-api/internal/shared/logger"
)

func main() {
	if err := run(); err != nil {
		fmt.Fprintf(os.Stderr, "erp-api: fatal: %v\n", err)
		os.Exit(1)
	}
}

func run() error {
	cfg, err := config.Load()
	if err != nil {
		return err
	}

	log, err := logger.New(cfg.App.Env)
	if err != nil {
		return fmt.Errorf("logger init: %w", err)
	}
	defer func() { _ = log.Sync() }()

	ctx, stop := signal.NotifyContext(context.Background(), os.Interrupt, syscall.SIGTERM)
	defer stop()

	// --- Postgres (pgx pool for health) + Ent ORM (database/sql for the ORM + outbox) ---
	dbPool, err := database.NewPool(ctx, cfg.Postgres)
	if err != nil {
		return fmt.Errorf("postgres pool: %w", err)
	}
	defer dbPool.Close()

	sqlDB, err := sql.Open("pgx", cfg.Postgres.URL)
	if err != nil {
		return fmt.Errorf("ent driver init: %w", err)
	}
	defer func() { _ = sqlDB.Close() }()
	sqlDB.SetMaxOpenConns(cfg.Postgres.MaxOpenConns)
	sqlDB.SetMaxIdleConns(cfg.Postgres.MaxIdleConns)
	sqlDB.SetConnMaxLifetime(cfg.Postgres.ConnMaxLifetime)

	orm := ent.NewClient(ent.Driver(entsql.OpenDB(dialect.Postgres, sqlDB)))
	defer func() { _ = orm.Close() }()

	// Auto-migrate only in dev when explicitly enabled; prod uses cmd/migrate (Atlas).
	if cfg.Postgres.RunMigrations {
		if err := orm.Schema.Create(ctx); err != nil {
			return fmt.Errorf("ent schema create: %w", err)
		}
		log.Info("ent schema auto-migrated (POSTGRES_RUN_MIGRATIONS=true)")
	}

	// --- Redis cache ---
	redisClient := cache.NewClient(cfg.Redis)
	defer func() { _ = redisClient.Close() }()

	// --- NATS + transactional outbox + tenant-sync consumers ---
	natsConn := mustNATS(log, cfg)
	if natsConn != nil {
		defer natsConn.Drain()
		if err := events.EnsureStream(ctx, natsConn, cfg.Events); err != nil {
			log.Warn("ensure erp stream failed", zap.Error(err))
		}
	}

	if natsConn != nil && cfg.Events.OutboxEnabled {
		repo := eventslib.NewSQLOutboxRepository(sqlDB)
		poller := eventslib.NewOutboxPoller(repo, eventslib.NewNATSAdapter(natsConn, log), log, eventslib.PollerConfig{
			BatchSize:  cfg.Events.OutboxBatchSize,
			PollPeriod: cfg.Events.OutboxPollPeriod,
		})
		poller.Start(ctx)
		log.Info("outbox publisher started",
			zap.Int("batch_size", cfg.Events.OutboxBatchSize),
			zap.Duration("poll_period", cfg.Events.OutboxPollPeriod))
	}

	tenantSyncer := usersync.NewTenantSyncer(orm, log)
	if natsConn != nil {
		idem := eventslib.NewIdempotencyStore(sqlDB)
		tenantConsumer := consumers.NewTenantSyncConsumer(log, tenantSyncer, idem)
		if err := tenantConsumer.Start(ctx, natsConn); err != nil {
			log.Warn("tenant-sync consumer start failed", zap.Error(err))
		}
	}

	// --- RBAC + handlers ---
	rbacService := rbac.NewService(orm, log)
	authHandler := handlers.NewAuthHandler(log, rbacService)
	healthHandler := handlers.NewHealthHandler(log, dbPool, redisClient, natsConn)
	brandingHandler := handlers.NewBrandingHandler(log)

	// HRM modules (Sprint 2 employees + Sprint 3 leave/attendance/recruitment/training/appraisals).
	notifyPublisher := events.NewPublisher(orm, cfg.Events.SourceService)
	employeesSvc := employees.NewService(orm)
	employeesHandler := handlers.NewEmployeesHandler(log, employeesSvc)
	leaveSvc := leave.NewService(orm, leave.NewOutboxNotifier(notifyPublisher))
	leaveHandler := handlers.NewLeaveHandler(log, leaveSvc)

	// Leave accrual cron (Go replacement for the accrue_leave management command).
	leave.NewAccrualCron(leaveSvc, log, cfg.Events.LeaveAccrualInterval).Start(ctx)

	// --- Auth middleware (SSO JWKS + optional S2S API key) ---
	authMiddleware, err := buildAuthMiddleware(cfg)
	if err != nil {
		return err
	}

	// --- Router ---
	r := chi.NewRouter()
	r.Use(chimw.RequestID, chimw.RealIP, chimw.Recoverer)
	r.Use(mw.CORS(cfg.HTTP.AllowedOrigins))

	// Public (no auth): health/metrics + login-page branding.
	r.Get("/healthz", healthHandler.Liveness)
	r.Get("/readyz", healthHandler.Readiness)
	r.Get("/metrics", healthHandler.Metrics)
	r.Route("/api/v1", func(api chi.Router) {
		brandingHandler.RegisterRoutes(api) // public branding
		// Authenticated surface.
		api.Group(func(priv chi.Router) {
			priv.Use(authMiddleware.RequireAuth)
			priv.Use(mw.OutletContext)
			authHandler.RegisterRoutes(priv)
			employeesHandler.RegisterRoutes(priv)
			leaveHandler.RegisterRoutes(priv)
		})
	})

	srv := &http.Server{
		Addr:         fmt.Sprintf("%s:%d", cfg.HTTP.Host, cfg.HTTP.Port),
		Handler:      r,
		ReadTimeout:  cfg.HTTP.ReadTimeout,
		WriteTimeout: cfg.HTTP.WriteTimeout,
		IdleTimeout:  cfg.HTTP.IdleTimeout,
	}

	errCh := make(chan error, 1)
	go func() {
		log.Info("erp-api listening", zap.String("addr", srv.Addr), zap.String("env", cfg.App.Env))
		if err := srv.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			errCh <- err
		}
	}()

	select {
	case err := <-errCh:
		return fmt.Errorf("http server: %w", err)
	case <-ctx.Done():
		log.Info("shutdown signal received")
	}

	shutdownCtx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	if err := srv.Shutdown(shutdownCtx); err != nil {
		return fmt.Errorf("graceful shutdown: %w", err)
	}
	log.Info("erp-api stopped cleanly")
	return nil
}

// mustNATS connects to NATS, logging (not failing) when events are disabled or the
// broker is unreachable — the service stays up and degrades gracefully.
func mustNATS(log *zap.Logger, cfg *config.Config) *nats.Conn {
	if !cfg.Events.Enabled {
		log.Warn("events disabled (EVENTS_ENABLED=false)")
		return nil
	}
	nc, err := events.Connect(cfg.Events)
	if err != nil {
		log.Warn("NATS connect failed; running without eventing", zap.Error(err))
		return nil
	}
	log.Info("connected to NATS", zap.String("url", cfg.Events.NATSURL))
	return nc
}

func buildAuthMiddleware(cfg *config.Config) (*authclient.AuthMiddleware, error) {
	authCfg := authclient.DefaultConfig(cfg.Auth.JWKSUrl, cfg.Auth.Issuer, cfg.Auth.Audience)
	authCfg.CacheTTL = cfg.Auth.JWKSCacheTTL
	authCfg.RefreshInterval = cfg.Auth.JWKSRefreshInterval

	validator, err := authclient.NewValidator(authCfg)
	if err != nil {
		return nil, fmt.Errorf("auth validator init: %w", err)
	}
	if cfg.Auth.EnableAPIKeyAuth {
		return authclient.NewAuthMiddlewareWithAPIKey(validator, authclient.NewAPIKeyValidator(cfg.Auth.ServiceURL, nil)), nil
	}
	return authclient.NewAuthMiddleware(validator), nil
}
