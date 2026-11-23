// Command server is the erp-api HTTP entrypoint. It wires the Sprint 1 foundation:
// config, Ent ORM (Postgres), Redis cache, NATS + transactional outbox, SSO/JWKS auth,
// tenant/outlet context, the tenant-sync consumers, and the public + authenticated routes.
package main

import (
	"context"
	"database/sql"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"entgo.io/ent/dialect"
	entsql "entgo.io/ent/dialect/sql"
	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"
	"github.com/google/uuid"
	_ "github.com/jackc/pgx/v5/stdlib" // register the "pgx" database/sql driver
	"github.com/nats-io/nats.go"
	httpSwagger "github.com/swaggo/http-swagger/v2"
	"go.uber.org/zap"

	sharedcache "github.com/Bengo-Hub/cache"
	httpware "github.com/Bengo-Hub/httpware"
	"github.com/Bengo-Hub/httpware/objectstore"
	"github.com/Bengo-Hub/httpware/tenantexport"
	authclient "github.com/Bengo-Hub/shared-auth-client"
	eventslib "github.com/Bengo-Hub/shared-events"
	sharedratelimit "github.com/Bengo-Hub/shared-ratelimit"

	"github.com/Bengo-Hub/erp-api/internal/config"
	"github.com/Bengo-Hub/erp-api/internal/ent"
	"github.com/Bengo-Hub/erp-api/internal/http/handlers"
	mw "github.com/Bengo-Hub/erp-api/internal/http/middleware"
	"github.com/Bengo-Hub/erp-api/internal/modules/appraisals"
	"github.com/Bengo-Hub/erp-api/internal/modules/approvals"
	"github.com/Bengo-Hub/erp-api/internal/modules/attendance"
	"github.com/Bengo-Hub/erp-api/internal/modules/business"
	"github.com/Bengo-Hub/erp-api/internal/modules/consumers"
	"github.com/Bengo-Hub/erp-api/internal/modules/contracts"
	"github.com/Bengo-Hub/erp-api/internal/modules/docs"
	"github.com/Bengo-Hub/erp-api/internal/modules/docs/sequence"
	"github.com/Bengo-Hub/erp-api/internal/modules/employees"
	"github.com/Bengo-Hub/erp-api/internal/modules/fx"
	"github.com/Bengo-Hub/erp-api/internal/modules/leave"
	"github.com/Bengo-Hub/erp-api/internal/modules/orgsettings"
	"github.com/Bengo-Hub/erp-api/internal/modules/payroll"
	"github.com/Bengo-Hub/erp-api/internal/modules/payrollsettings"
	"github.com/Bengo-Hub/erp-api/internal/modules/performance"
	"github.com/Bengo-Hub/erp-api/internal/modules/rbac"
	"github.com/Bengo-Hub/erp-api/internal/modules/recruitment"
	"github.com/Bengo-Hub/erp-api/internal/modules/reports"
	"github.com/Bengo-Hub/erp-api/internal/modules/staffpurchase"
	"github.com/Bengo-Hub/erp-api/internal/modules/tasks"
	"github.com/Bengo-Hub/erp-api/internal/modules/training"
	platformauth "github.com/Bengo-Hub/erp-api/internal/platform/auth"
	"github.com/Bengo-Hub/erp-api/internal/platform/cache"
	"github.com/Bengo-Hub/erp-api/internal/platform/database"
	"github.com/Bengo-Hub/erp-api/internal/platform/events"
	"github.com/Bengo-Hub/erp-api/internal/platform/lookups"
	"github.com/Bengo-Hub/erp-api/internal/platform/media"
	subs "github.com/Bengo-Hub/erp-api/internal/platform/subscriptions"
	"github.com/Bengo-Hub/erp-api/internal/platform/treasury"
	"github.com/Bengo-Hub/erp-api/internal/services/usersync"
	"github.com/Bengo-Hub/erp-api/internal/shared/logger"

	_ "github.com/Bengo-Hub/erp-api/internal/http/docs" // generated OpenAPI/Swagger spec (swag init)
)

// @title           ERP API
// @version         1.0
// @description     Codevertex ERP (HR/Ops) backend — employees, payroll, leave, attendance,
// @description     recruitment, training, appraisals, approvals, tasks, reports. OAuth via SSO,
// @description     notifications via notifications-service.
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

	// Schema changes only through cmd/migrate (direct connection, advisory lock). An unlocked
	// in-process auto-migrate on every replica start was removed.

	// --- Redis cache + shared cache-aside helper (read-through for branding etc.) ---
	redisClient := cache.NewClient(cfg.Redis)
	defer func() { _ = redisClient.Close() }()
	cacheAside := sharedcache.New(redisClient, log)
	// Lease client for the once-per-period job guards (fx, leave accrual).
	sharedcache.SetLeaseClient(redisClient)

	// Distributed rate limiter (shared GCRA, exact across replicas, per-pod fallback bucket when
	// Redis is down).
	rateLimiter := mw.NewRateLimiter(redisClient, cfg.RateLimit, log)
	if cfg.RateLimit.Enabled {
		log.Info("rate limiting enabled",
			zap.Int("per_minute", cfg.RateLimit.RequestsPerMinute),
			zap.Int("per_hour", cfg.RateLimit.RequestsPerHour),
			zap.Int("sensitive_per_minute", cfg.RateLimit.PaymentRequestsPerMinute))
	}

	// --- NATS + transactional outbox + tenant-sync consumers ---
	natsConn := mustNATS(log, cfg)
	if natsConn != nil {
		defer natsConn.Drain()
		if err := events.EnsureStream(ctx, natsConn, cfg.Events); err != nil {
			log.Warn("ensure erp stream failed", zap.Error(err))
		}
		// A revoked or rotated API key stops working on every replica at once, not after the
		// validator cache TTL.
		_ = eventslib.NewBroadcaster(log, natsConn, "auth").Subscribe("apikey.changed", func(m eventslib.BroadcastMessage) {
			authclient.InvalidateAPIKeyHash(string(m.Data))
		})
	}

	if natsConn != nil && cfg.Events.OutboxEnabled {
		// JetStream (not core) so publishes are ACKed into the erp stream — consumers
		// (treasury GL, notifications) are durable JS subscribers and need replay.
		js, jsErr := natsConn.JetStream()
		if jsErr != nil {
			return fmt.Errorf("jetstream init for outbox poller: %w", jsErr)
		}
		repo := eventslib.NewSQLOutboxRepository(sqlDB)
		poller := eventslib.NewOutboxPoller(repo, eventslib.NewJetStreamAdapter(js, log), log, eventslib.PollerConfig{
			BatchSize:  cfg.Events.OutboxBatchSize,
			PollPeriod: cfg.Events.OutboxPollPeriod,
		})
		poller.Start(ctx)
		log.Info("outbox publisher started",
			zap.Int("batch_size", cfg.Events.OutboxBatchSize),
			zap.Duration("poll_period", cfg.Events.OutboxPollPeriod))
	}

	tenantSyncer := usersync.NewTenantSyncer(orm, log)
	authUserEmployeesSvc := employees.NewService(orm)
	if natsConn != nil {
		idem := eventslib.NewIdempotencyStore(sqlDB)
		// One shared plan check for every erp consumer: no shadow, outlet or employee rows for a
		// tenant whose plan does not include erp.
		erpEntitlement := authclient.NewEntitlementClient(cfg.Services.SubscriptionsURL, cfg.Auth.APIKey)
		erpEntitled := func(ctx context.Context, tenantID uuid.UUID) bool {
			return erpEntitlement.UsesService(ctx, tenantID.String(), "erp")
		}
		tenantConsumer := consumers.NewTenantSyncConsumer(log, tenantSyncer, idem)
		tenantConsumer.Entitled = erpEntitled
		if err := tenantConsumer.Start(ctx, natsConn); err != nil {
			log.Warn("tenant-sync consumer start failed", zap.Error(err))
		}
		// Project auth-api users into erp employees (keyed on the auth user id) so a
		// tenant's employee roster is populated from SSO instead of empty placeholders.
		authUserConsumer := consumers.NewAuthUserSyncConsumer(log, authUserEmployeesSvc, idem)
		authUserConsumer.Entitled = erpEntitled
		if err := authUserConsumer.Start(ctx, natsConn); err != nil {
			log.Warn("auth-user-sync consumer start failed", zap.Error(err))
		}
		// tenant.purge (dormancy, a deleted tenant, a declined registration): delete every row
		// erp holds for the tenant (auth_tenants included), by the shared schema-driven purger.
		if js, err := natsConn.JetStream(); err == nil {
			purger := &eventslib.TenantPurger{DB: sqlDB, Log: log.Named("tenant-purge"), Service: "erp"}
			if err := purger.Subscribe(js); err != nil {
				log.Warn("tenant purge consumer not started", zap.Error(err))
			}
		}
	}

	// --- RBAC + handlers ---
	rbacService := rbac.NewService(orm, log)
	handlers.SetRBACService(rbacService) // enable local erp-permission enforcement in requirePermission
	authHandler := handlers.NewAuthHandler(log, rbacService)
	rbacHandler := handlers.NewRBACHandler(log, rbacService)
	// Tenant backups are made from the SSO client area (auth-api collects this service's
	// /api/v1/s2s/tenant-export); the platform pg_dumpall covers disaster recovery.
	healthHandler := handlers.NewHealthHandler(log, dbPool, redisClient, natsConn)
	// Branding read-through: auth-api SoT, Redis-cached.
	brandingClient := platformauth.NewBrandingClient(cfg.Auth.ServiceURL, cacheAside, log)
	brandingHandler := handlers.NewBrandingHandler(log, brandingClient)

	// HRM modules (Sprint 2 employees + Sprint 3 leave/attendance/recruitment/training/appraisals).
	notifyPublisher := events.NewPublisher(orm, cfg.Events.SourceService)
	employeesSvc := employees.NewService(orm)
	handlers.SetEmployeeResolver(employeesSvc.EmployeeIDForExternalUser) // ESS self-scoping (?mine=true)
	employeesHandler := handlers.NewEmployeesHandler(log, employeesSvc)
	orgSettingsHandler := handlers.NewOrgSettingsHandler(log, orgsettings.NewService(orm))
	contractsHandler := handlers.NewContractsHandler(log, contracts.NewService(orm))

	// Payroll: engine service (reuses payroll-settings for rate resolution) + disburser
	// (publishes the GL event + best-effort treasury S2S payout).
	// Global statutory formulas live under the synthetic system tenant; tenants without their
	// own current formula inherit it (feedback_shared_core_reference_data). uuid.Nil = no fallback.
	systemTenant, _ := uuid.Parse(cfg.Payroll.SystemTenantID)
	payrollSettingsSvc := payrollsettings.NewService(orm, systemTenant)
	treasuryClient := treasury.NewClient(cfg.Services.TreasuryURL, cfg.Auth.APIKey, log)
	// Claim approval checks treasury budgets first (fails open when treasury is unreachable).
	payrollSvc := payroll.NewService(orm, payrollSettingsSvc).WithPublisher(notifyPublisher).WithLogger(log.Named("payroll")).WithBudgetChecker(treasuryClient)
	employeesHandler.WithTreasury(treasuryClient) // enables /hrm/banks/* verify proxy
	payrollDisburser := payroll.NewDisburser(orm, notifyPublisher, treasuryClient, log)
	// POS↔ERP staff-credit: premium-gated recoverable created S2S by pos-api (staff_fund_from_salary).
	subsGate := subs.NewClient(cfg.Services.SubscriptionsURL, cfg.Auth.APIKey, log)
	staffPurchaseSvc := staffpurchase.NewService(orm, employeesSvc, subsGate, notifyPublisher, log)
	staffPurchaseHandler := handlers.NewStaffPurchaseHandler(log, staffPurchaseSvc)
	// HR files (resumes, claim receipts, employee documents) on the shared object storage, all
	// private (httpware/objectstore).
	media.RegisterMediaTypes()
	objStore, err := objectstore.New("erp", objectstore.FromEnv())
	if err != nil {
		return fmt.Errorf("object storage: %w", err)
	}
	mediaStore := media.NewStore(objStore)
	// HR document upload/streaming + branded employment-contract PDF (tenant letterhead).
	employeesHandler.WithMedia(mediaStore).WithBranding(brandingClient)
	// Cost-allocation lookups: proxy projects-service + treasury cost-centers (JWT-forwarded);
	// falls back to ERP-derived distinct ids when an upstream is unconfigured/unavailable.
	lookupsClient := lookups.NewClient(cfg.Services.ProjectsURL, cfg.Services.TreasuryURL, cfg.Auth.APIKey, log)
	// Payroll "process" runs as a background job (progress streamed over SSE). Jobs stop with
	// the server and are marked interrupted; every pod sweeps runs whose heartbeat went stale.
	jobsCtx, stopJobs := context.WithCancel(context.Background())
	defer stopJobs()
	payrollJobs := payroll.NewJobRunner(jobsCtx, payrollSvc, log.Named("payroll.jobs"))
	payrollJobs.StartSweeper()
	payrollHandler := handlers.NewPayrollHandler(log, payrollSvc, payrollDisburser).
		WithMedia(mediaStore).WithLookups(lookupsClient).WithJobs(payrollJobs)
	payrollSettingsHandler := handlers.NewPayrollSettingsHandler(log, payrollSettingsSvc, orm)
	leaveSvc := leave.NewService(orm, leave.NewOutboxNotifier(notifyPublisher)).WithSystemTenant(systemTenant)
	leaveHandler := handlers.NewLeaveHandler(log, leaveSvc)
	attendanceSvc := attendance.NewService(orm).WithPublisher(notifyPublisher).WithLogger(log.Named("attendance"))
	attendanceHandler := handlers.NewAttendanceHandler(log, attendanceSvc).WithMedia(mediaStore)
	// Rotation advance, auto-absent per tenant and day, and the punch processor sweep.
	attendance.NewCron(attendanceSvc, redisClient, log, 0).Start(ctx)
	employeesHandler.WithAttendance(attendanceSvc) // PUT /hrm/employees/{id}/device-pin
	// ZKTeco PUSH (ADMS) endpoints for biometric terminals: public, keyed by device serial.
	iclockHandler := handlers.NewICLockHandler(log, attendanceSvc)
	recruitmentSvc := recruitment.NewService(orm).WithNotifier(events.NewNotifications(notifyPublisher))
	recruitmentHandler := handlers.NewRecruitmentHandler(log, recruitmentSvc, mediaStore)
	careersHandler := handlers.NewCareersHandler(log, recruitmentSvc) // PUBLIC careers portal
	trainingHandler := handlers.NewTrainingHandler(log, training.NewService(orm))
	appraisalsSvc := appraisals.NewService(orm).WithSystemTenant(systemTenant)
	appraisalsHandler := handlers.NewAppraisalsHandler(log, appraisalsSvc)
	performanceHandler := handlers.NewPerformanceHandler(log, performance.NewService(orm))

	// Generic approvals engine wired into leave and appraisals (replaces their direct
	// approve/reject when a tenant configures a workflow).
	approvalsSvc := approvals.NewService(orm, approvals.NewOutboxEmitter(notifyPublisher))
	approvalsHandler := handlers.NewApprovalsHandler(log, approvalsSvc)
	leaveSvc.SetApprovals(approvalsSvc)
	appraisalsSvc.SetApprovals(approvalsSvc)
	// Attendance regularisations and overtime requests decide through the approvals engine;
	// their hooks apply the change when /approvals finishes a request.
	attendanceSvc.SetApprovals(approvalsSvc)

	// Sprint 4: internal task tracker (distinct from projects-service).
	tasksHandler := handlers.NewTasksHandler(log, tasks.NewService(orm))

	// Sprint 4: reporting layer (P9/P10A/statutory/bank/summaries) for the erp-ui report-runner.
	reportsHandler := handlers.NewReportsHandler(log, reports.NewService(orm))

	// Document generation (payslip PDF + report PDF/Excel export). Mirrors treasury-api's
	// docs module: branded PDF/CSV/XLSX via fpdf/excelize + atomic doc-number sequences.
	docService := &docs.DocumentService{}
	docSeq := sequence.New(sqlDB, orm)
	// Auto-issue meaningful staff numbers (SLUG/YYYY/###) for new + JIT-provisioned employees.
	employeesSvc.WithSequence(docSeq)
	authUserEmployeesSvc.WithSequence(docSeq)
	documentsHandler := handlers.NewDocumentsHandler(log, orm, brandingClient, payrollSvc, docService, docSeq).
		WithNotifications(events.NewNotifications(notifyPublisher)).
		WithTreasury(treasuryClient)
	reportsHandler.SetDocuments(documentsHandler) // enable /reports/{type}/export

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
	// Not chi RealIP: it trusts a client-supplied True-Client-IP / X-Forwarded-For.
	r.Use(sharedratelimit.TrustedRealIP)
	// Tolerate DRF-style trailing slashes (erp-ui calls /api/v1/hrm/employees/) — chi routes are
	// registered without trailing slashes, so strip before matching to avoid 404s.
	r.Use(chimw.StripSlashes)
	r.Use(httpware.RequestID)
	r.Use(httpware.Logging(log))
	r.Use(httpware.Recover(log))
	// gzip JSON responses and bound per-request duration, like the other Go services. Streams
	// (SSE, and the tenant export auth-api reads for SSO tenant backups, which may run for
	// minutes and is gzipped already) skip both (httpware.BypassForStreaming).
	r.Use(httpware.BypassForStreaming(chimw.Compress(5)))
	r.Use(httpware.BypassForStreaming(chimw.Timeout(30 * time.Second)))
	// Guard against a credentialed wildcard CORS misconfiguration: AllowCredentials:true with
	// Origin "*" lets any site make authenticated cross-origin calls. Fail fast at boot.
	for _, o := range cfg.HTTP.AllowedOrigins {
		if strings.TrimSpace(o) == "*" {
			return fmt.Errorf("config: HTTP_ALLOWED_ORIGINS must not contain \"*\" with credentialed CORS")
		}
	}
	r.Use(httpware.CORS(httpware.StandardCORS(cfg.HTTP.AllowedOrigins)))

	// Public (no auth): health/metrics + login-page branding.
	r.Get("/healthz", healthHandler.Liveness)
	r.Get("/readyz", healthHandler.Readiness)
	r.Get("/metrics", healthHandler.Metrics)
	// Biometric devices push to /iclock/* (their server address is usually set without a path);
	// the same routes are also served under /api/v1. No JWT: the handler admits registered,
	// active serials only, and each serial plus IP has its own rate budget.
	deviceLimit := rateLimiter.Middleware(handlers.DeviceKey, cfg.RateLimit.RequestsPerMinute, time.Minute)
	// A per-address ceiling in front, so rotating made-up serials cannot dodge the per-serial
	// budget. Sized for a site with several terminals behind one NAT address.
	deviceIPLimit := rateLimiter.Middleware(handlers.DeviceIPKey, 10*cfg.RateLimit.RequestsPerMinute, time.Minute)
	r.Group(func(dr chi.Router) {
		dr.Use(deviceIPLimit, deviceLimit)
		iclockHandler.RegisterRoutes(dr)
	})
	// Tenant export for auth-api's SSO tenant backups; the handler checks INTERNAL_SERVICE_KEY
	// itself (httpware/tenantexport). Not mounted without a key.
	if cfg.Auth.APIKey != "" {
		r.Get("/api/v1/s2s/tenant-export", tenantexport.Handler(sqlDB,
			tenantexport.Options{Service: "erp", InternalKey: cfg.Auth.APIKey}).ServeHTTP)
	}
	// API docs at the platform-standard /v1/docs/ (like all Go services); base URL redirects there.
	r.Get("/v1/docs/*", httpSwagger.Handler(httpSwagger.URL("/v1/docs/doc.json")))
	r.Get("/", func(w http.ResponseWriter, req *http.Request) {
		http.Redirect(w, req, "/v1/docs/", http.StatusFound)
	})
	r.Route("/api/v1", func(api chi.Router) {
		brandingHandler.RegisterRoutes(api) // public branding
		api.Group(func(dr chi.Router) {
			dr.Use(deviceIPLimit, deviceLimit)
			iclockHandler.RegisterRoutes(dr)
		})
		// Public careers portal (no auth): open postings + applications. The apply (write) route is
		// IP-rate-limited (10/hour) to deter spam; reads are unthrottled.
		careersHandler.RegisterRoutes(api, rateLimiter.IPRateLimiter(10, time.Hour))
		// Authenticated surface.
		api.Group(func(priv chi.Router) {
			priv.Use(authMiddleware.RequireAuth)
			// Per-tenant sliding-window limiter: the fair multi-tenant default so one busy
			// tenant cannot starve others. Runs after RequireAuth so the tenant is resolved
			// from validated JWT claims (falls back to IP for unauthenticated edge cases).
			priv.Use(rateLimiter.TenantRateLimiter(cfg.RateLimit.RequestsPerMinute, time.Minute))
			priv.Use(rateLimiter.IPRateLimiter(cfg.RateLimit.RequestsPerHour, time.Hour))
			// Subscription gate: block mutations for tenants without an active subscription
			// (reads still pass). Platform owners, demo, service-charge, and explicitly-exempt
			// tenants bypass via the shared IsSubscriptionActive funnel — a tenant superuser does
			// NOT bypass. Matches the inline enforcement in logistics/marketflow/projects +
			// TruLoad's SubscriptionEnforcementMiddleware.
			priv.Use(authclient.RequireActiveSubscriptionForMutationsWithGrace(7))
			priv.Use(mw.OutletContext)
			priv.Use(mw.EnsureServiceUser(rbacService, tenantSyncer, log)) // Trinity L3: JIT-sync erp roles + tenant shadow from SSO

			// auth/me must stay reachable even for a tenant whose plan doesn't include ERP at all
			// (kept OUTSIDE the module gate below), so the frontend can bootstrap identity/roles
			// and show a graceful "not included in your plan" screen instead of a raw 403 on its
			// very first authenticated call.
			authHandler.RegisterRoutes(priv)

			// Module gate: block the WHOLE erp module (reads and writes alike) for a tenant whose
			// plan never included ERP at all (e.g. PowerSuite Basic — ERP unlocks at Professional).
			// Distinct from the mutations-only gate above and from per-feature locks on payroll/
			// attendance/etc. below: without this, any SSO user of any tenant could still reach
			// erp-api's basic, ungated routes regardless of their plan.
			//
			// 2026-09-11: caused a fleet-wide outage on first deploy (every already-issued JWT
			// lacked the brand-new active_service_tags claim). Restored after all active sessions
			// were force-revoked so every request now carries a freshly-minted token with the
			// claim populated — see auth-api revocation runbook.
			priv.Group(func(erp chi.Router) {
				erp.Use(authclient.RequireServiceAccess("erp"))
				// Mutations-only annual support-fee gate for a perpetual/one-time-license tenant
				// (e.g. boi-enterprises on POWERSUITE_DUKA_GOLD_ONE_TIME) whose support fee has
				// gone unpaid past its 7-day grace window — independent axis from the
				// subscription gate (a one-time license never expires, so that gate alone never
				// catches this). No-ops for every tenant without a support-fee obligation.
				erp.Use(authclient.RequireSupportFeeCurrentForMutations(7))

				employeesHandler.RegisterRoutes(erp)
				orgSettingsHandler.RegisterRoutes(erp)
				contractsHandler.RegisterRoutes(erp)
				payrollSettingsHandler.RegisterRoutes(erp)
				staffPurchaseHandler.RegisterRoutes(erp) // POS↔ERP staff-credit (S2S + reconcile)
				leaveHandler.RegisterRoutes(erp)
				attendanceHandler.RegisterRoutes(erp)
				recruitmentHandler.RegisterRoutes(erp)
				trainingHandler.RegisterRoutes(erp)
				appraisalsHandler.RegisterRoutes(erp)
				performanceHandler.RegisterRoutes(erp)
				approvalsHandler.RegisterRoutes(erp)
				tasksHandler.RegisterRoutes(erp)
				reportsHandler.RegisterRoutes(erp)
				documentsHandler.RegisterRoutes(erp)
				businessHandler.RegisterRoutes(erp)
				rbacHandler.RegisterRoutes(erp) // service-level role/permission management

				// Sensitive surfaces (money paths + external fetches) get
				// an ADDITIONAL stricter per-endpoint+IP limiter on top of the per-tenant budget.
				sensitiveLimit := cfg.RateLimit.PaymentRequestsPerMinute
				erp.Group(func(s chi.Router) {
					s.Use(rateLimiter.EndpointRateLimiter("payroll", sensitiveLimit, time.Minute))
					payrollHandler.RegisterRoutes(s)
				})
				erp.Group(func(s chi.Router) {
					s.Use(rateLimiter.EndpointRateLimiter("fx", sensitiveLimit, time.Minute))
					fxHandler.RegisterRoutes(s)
				})
			})
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
	// Interrupt background payroll runs and wait (bounded) for them to record that.
	stopJobs()
	jobsDone := make(chan struct{})
	go func() { payrollJobs.Wait(); close(jobsDone) }()
	select {
	case <-jobsDone:
	case <-time.After(10 * time.Second):
		log.Warn("payroll runs did not stop in time; the sweeper will mark them interrupted")
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
