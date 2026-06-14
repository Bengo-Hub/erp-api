# Sprint 1 — Foundation (Go scaffold, auth, tenancy, eventing)

> Stand up the new Go `erp-service/erp-api` skeleton on the platform patterns so every later sprint
> plugs domain modules into a working server. No HR domain logic yet — just the rails.
> References: `revamp-plan.md`, `architecture.md` (TARGET), `integrations.md`,
> `D:\Projects\Codevertex\inventory-service\inventory-api` (copy this layout).

## Goals
- A deployable Go service that boots, connects DB/Redis/NATS, serves health/metrics, validates SSO
  JWTs, resolves tenant/outlet context, and runs the transactional outbox + tenant-sync consumers.
- Zero tenant-isolation debt from day one: the tenant middleware + base query helpers make
  `tenant_id` filtering the default, not an afterthought (fixes `gaps-and-bugs.md §1.4, §4`).

## Scope
- `cmd/api/main.go`, `cmd/migrate/main.go`, `cmd/seed/main.go`.
- `internal/app/app.go` wiring; `internal/config/config.go` (envconfig: App/HTTP/Postgres/Redis/
  Events/Auth/Services/Media). Mirror the Django env vars in `architecture.md §5` (DB, REDIS_URL,
  SSO_*, AUTH_*, INTERNAL_SERVICE_KEY, SERVICE_URLS, EVENTS_*).
- `internal/http/router` → `/api/v1/...` namespaces matching `urls.py` (auth, hrm, approvals,
  business, core, addresses, integrations, tasks, errors, cache).
- httpware middleware chain: request-id, recovery, CORS (secure defaults — **no** credentialed
  wildcard, fixing §1.3), structured zap logging.
- `platform/auth`: shared-auth-client JWKS validation + `Claims`; `services/usersync` JIT
  `CustomUser`/`AuthTenant`/`AuthOutlet` shadow provisioning (port `sso.py` + `tenant_sync.py`,
  **reconciling roles every login** — add+remove — fixing §1.5).
- Tenant/outlet middleware: `claims.TenantID` with platform-owner `?tenantId=` override + `X-Outlet-ID`
  (port `TenantOutletContextMiddleware`). Subscription-gate middleware (mutations-only, copy inventory-api).
- `platform/events`: shared-events `OutboxPoller` against an `outbox_events` Ent table; NATS connect;
  explicit consumer registry (fixes the "silent no handlers" §3) with `auth.tenant.>` / `auth.outlet.>`
  consumers upserting tenant/outlet shadows; DLQ + max-deliver policy.
- `platform/cache` (Redis), `platform/treasury` + `platform/auth` typed S2S clients
  (shared-service-client; internal key + JWT/tenant propagation; **no POST auto-retry** unless idempotent).
- `GET /api/v1/auth/me/` (port `auth_me.py`: service roles = Ent roles, bare-codename permissions).

## Endpoints
- `GET /api/v1/core/health/`, `GET /api/v1/integrations/health/` (no auth).
- `GET /metrics` (Prometheus).
- `GET /api/v1/auth/me/` (JWT).
- `GET /api/v1/business/public-branding/` (no auth — read-through auth-api branding cache).

## Ent schemas (this sprint)
- Core/identity shadows: `CustomUser` (UUID PK, `external_id` unique, signature/prefs fields),
  `AuthTenant` (UUID = auth-api tenant), `AuthOutlet` (UUID, `tenant_id` FK).
- RBAC: `Role`, `Permission`, role↔permission, user↔role (mirror inventory-api
  `inventoryrole`/`inventorypermission`).
- `OutboxEvent` (UUID, subject, aggregate_type/id, tenant_id, payload JSON, status, attempts, error,
  created_at, published_at) + retention fields.
- `IdempotencyKey` store (for S2 disburse + consumers).
- Reference data placeholders consumed by later sprints: `Region`, `Department`, `Project`,
  `BankInstitution`, `BankBranch` (so `cmd/seed` can run).

## Events
- IN: `auth.tenant.>` → upsert `AuthTenant`; `auth.outlet.>` → upsert/archive `AuthOutlet`.
- Outbox publishing path proven with a no-op test subject; envelope identical to `integrations.md §1`.

## cmd/seed
- 14 RBAC roles + HR-scoped permissions (mirror `seed_rbac_roles.py:ROLE_SPECS`; **exclude** stale
  decomposed perms). This replaces copying `auth_group`/`auth_permission`.

## Acceptance criteria
- `docker run` boots; `/core/health/` 200; `/metrics` exposed.
- Valid auth-api JWT → `/auth/me` returns roles+permissions; invalid → 401; missing on public route → 200.
- Platform owner `?tenantId=` override resolves; non-platform user is pinned to `claims.TenantID`.
- Publishing a test event writes an `outbox_events` row → OutboxPoller publishes to NATS → marked published.
- `auth.tenant.created` consumed → `AuthTenant` row appears (tenant-isolated).
- Atlas migrations apply cleanly to an empty `erp` DB; `cmd/seed` populates roles.
- No secret in repo; CORS rejects credentialed wildcard.

## Dependencies
- None (first sprint). Requires access to auth-api JWKS, NATS, Postgres, Redis in dev.
- Blocks: all subsequent sprints.
