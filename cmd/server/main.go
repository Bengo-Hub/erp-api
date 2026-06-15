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
	httpSwagger "github.com/swaggo/http-swagger/v2"
	"go.uber.org/zap"

	sharedcache "github.com/Bengo-Hub/cache"
	httpware "github.com/Bengo-Hub/httpware"
	authclient "github.com/Bengo-Hub/shared-auth-client"
	eventslib "github.com/Bengo-Hub/shared-events"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/http/handlers"
	mw "github.com/Bengo-Hub/erp-api/internal/http/middleware"
	"github.com/Bengo-Hub/erp-api/internal/modules/appraisals"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
	"github.com/Bengo-Hub/erp-api/internal/modules/business"
	"github.com/Bengo-Hub/erp-api/internal/modules/consumers"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/modules/fx"
	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
	"github.com/Bengo-Hub/erp-api/internal/modules/orgsettings"
	"github.com/Bengo-Hub/erp-api/internal/modules/performance"
	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
	"github.com/Bengo-Hub/erp-api/internal/modules/recruitment"
	"github.com/Bengo-Hub/erp-api/internal/modules/reports"
	"github.com/Bengo-Hub/erp-api/internal/modules/tasks"
	"github.com/Bengo-Hub/erp-api/internal/modules/training"
	platformauth "github.com/Bengo-Hub/erp-api/internal/platform/auth"
	"github.com/Bengo-Hub/erp-api/internal/platform/cache"
	"github.com/Bengo-Hub/erp-api/internal/platform/database"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
	"github.com/Bengo-Hub/erp-api/internal/platform/media"
	"github.com/Bengo-Hub/erp-api/internal/services/usersync"
	"github.com/Bengo-Hub/erp-api/internal/shared/logger"

	_ "github.com/Bengo-Hub/erp-api/internal/http/docs" // generated OpenAPI/Swagger spec (swag init)
)

// @title           ERP API
// @version         1.0
// @description     Codevertex ERP (HR/Ops) backend — employees, payroll, leave, attendance,
// @description     recruitment, training, appraisals, approvals, tasks, reports. Go rebuild of the
// @description     legacy Django ERP. OAuth via SSO, notifications via notifications-service.
// @BasePath        /api/v1
// @securityDefinitions.apikey BearerAuth
// @in              header
// @name            Authorization
// @description     JWT from auth-service (SSO). Format: "Bearer {token}".
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

	sqlDB, err := sql.Open("pgx", cfg.Postgres.DSN())
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

	// --- Redis cache + shared cache-aside helper (read-through for branding etc.) ---
	redisClient := cache.NewClient(cfg.Redis)
	defer func() { _ = redisClient.Close() }()
	cacheAside := sharedcache.New(redisClient, log)

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
	// Branding read-through: auth-api SoT, Redis-cached (plan §0a-map).
	brandingClient := platformauth.NewBrandingClient(cfg.Auth.ServiceURL, cacheAside, log)
	brandingHandler := handlers.NewBrandingHandler(log, brandingClient)

	// HRM modules (Sprint 2 employees + Sprint 3 leave/attendance/recruitment/training/appraisals).
	notifyPublisher := events.NewPublisher(orm, cfg.Events.SourceService)
	employeesSvc := employees.NewService(orm)
	employeesHandler := handlers.NewEmployeesHandler(log, employeesSvc)
	orgSettingsHandler := handlers.NewOrgSettingsHandler(log, orgsettings.NewService(orm))
	leaveSvc := leave.NewService(orm, leave.NewOutboxNotifier(notifyPublisher))
	leaveHandler := handlers.NewLeaveHandler(log, leaveSvc)
	attendanceHandler := handlers.NewAttendanceHandler(log, attendance.NewService(orm))
	mediaStore := media.NewStore(cfg.Media.Root, cfg.Media.URLBase)
	recruitmentHandler := handlers.NewRecruitmentHandler(log, recruitment.NewService(orm), mediaStore)
	trainingHandler := handlers.NewTrainingHandler(log, training.NewService(orm))
	appraisalsSvc := appraisals.NewService(orm)
	appraisalsHandler := handlers.NewAppraisalsHandler(log, appraisalsSvc)
	performanceHandler := handlers.NewPerformanceHandler(log, performance.NewService(orm))

	// Sprint 4: generic approvals engine wired into leave + appraisals (replaces their
	// Sprint-3 direct approve/reject when a tenant configures a workflow).
	approvalsSvc := approvals.NewService(orm, approvals.NewOutboxEmitter(notifyPublisher))
	approvalsHandler := handlers.NewApprovalsHandler(log, approvalsSvc)
	leaveSvc.SetApprovals(approvalsSvc)
	appraisalsSvc.SetApprovals(approvalsSvc)

	// Sprint 4: internal task tracker (distinct from projects-service).
	tasksHandler := handlers.NewTasksHandler(log, tasks.NewService(orm))

	// Sprint 4: reporting layer (P9/P10A/statutory/bank/summaries) for the erp-ui report-runner.
	reportsHandler := handlers.NewReportsHandler(log, reports.NewService(orm))

	// Sprint 4: slim business config (company settings + document numbering).
	businessHandler := handlers.NewBusinessHandler(log, business.NewService(orm))

	// Sprint 4: FX rate fetch (cron) + read endpoints.
	fxSvc := fx.NewService(orm, log)
	fxHandler := handlers.NewFXHandler(log, fxSvc)
	fx.NewCron(fxSvc, log, cfg.Events.FXFetchInterval).Start(ctx)

	// Leave accrual cron (Go replacement for the accrue_leave management command).
	leave.NewAccrualCron(leaveSvc, log, cfg.Events.LeaveAccrualInterval).Start(ctx)

	// --- Auth middleware (SSO JWKS + optional S2S API key) ---
	authMiddleware, err := buildAuthMiddleware(cfg)
	if err != nil {
		return err
	}

	// --- Router (shared httpware middleware: request-id, structured logging,
	// panic recovery, CORS — replaces the hand-rolled chi/CORS stack). ---
	r := chi.NewRouter()
	r.Use(chimw.RealIP)
	// Tolerate DRF-style trailing slashes (erp-ui calls /api/v1/hrm/employees/) — chi routes are
	// registered without trailing slashes, so strip before matching to avoid 404s.
	r.Use(chimw.StripSlashes)
	r.Use(httpware.RequestID)
	r.Use(httpware.Logging(log))
	r.Use(httpware.Recover(log))
	r.Use(httpware.CORS(httpware.CORSConfig{
		AllowedOrigins:   cfg.HTTP.AllowedOrigins,
		AllowedMethods:   []string{"GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Authorization", "Content-Type", "X-API-Key", "X-Tenant-ID", "X-Tenant-Slug", "X-Outlet-ID", "X-Request-ID", "X-Requested-With"},
		AllowCredentials: true,
		MaxAge:           600,
	}))

	// Public (no auth): health/metrics + login-page branding.
	r.Get("/healthz", healthHandler.Liveness)
	r.Get("/readyz", healthHandler.Readiness)
	r.Get("/metrics", healthHandler.Metrics)
	// API docs at the platform-standard /v1/docs/ (like all Go services); base URL redirects there.
	r.Get("/v1/docs/*", httpSwagger.Handler(httpSwagger.URL("/v1/docs/doc.json")))
	r.Get("/", func(w http.ResponseWriter, req *http.Request) {
		http.Redirect(w, req, "/v1/docs/", http.StatusFound)
	})
	r.Route("/api/v1", func(api chi.Router) {
		brandingHandler.RegisterRoutes(api) // public branding
		// Authenticated surface.
		api.Group(func(priv chi.Router) {
			priv.Use(authMiddleware.RequireAuth)
			priv.Use(mw.OutletContext)
			authHandler.RegisterRoutes(priv)
			employeesHandler.RegisterRoutes(priv)
			orgSettingsHandler.RegisterRoutes(priv)
			leaveHandler.RegisterRoutes(priv)
			attendanceHandler.RegisterRoutes(priv)
			recruitmentHandler.RegisterRoutes(priv)
			trainingHandler.RegisterRoutes(priv)
			appraisalsHandler.RegisterRoutes(priv)
			performanceHandler.RegisterRoutes(priv)
			approvalsHandler.RegisterRoutes(priv)
			tasksHandler.RegisterRoutes(priv)
			reportsHandler.RegisterRoutes(priv)
			businessHandler.RegisterRoutes(priv)
			fxHandler.RegisterRoutes(priv)
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
