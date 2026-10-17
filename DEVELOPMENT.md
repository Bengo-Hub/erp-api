# Development guide

Local setup, common tasks and troubleshooting for `erp-api` (Go).

## Prerequisites

- Go 1.26
- PostgreSQL 15 or newer
- Redis (optional locally; the cache degrades without it)
- NATS with JetStream (optional; set `EVENTS_ENABLED=false` to run without it)

## Setup

```bash
git clone https://github.com/Bengo-Hub/erp-api.git
cd erp-api
go mod download

# Postgres and Redis through Docker, if you have no local instances
docker run -d --name erp-pg -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=bengo_erp -p 5432:5432 postgres:17
docker run -d --name erp-redis -p 6379:6379 redis:7
```

Configuration is environment variables with local defaults; the full list is in
[docs/architecture.md](docs/architecture.md) section 6 and `internal/config/config.go`.

## Run

```bash
export POSTGRES_URL='postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable'
export POSTGRES_MIGRATE_URL="$POSTGRES_URL"

go run ./cmd/migrate        # apply Atlas migrations (the server does not migrate in prod)
go run ./cmd/seed           # RBAC permissions and system roles
go run ./cmd/seed-payroll   # global statutory rates
go run ./cmd/seed-defaults  # per-tenant HR reference data
go run ./cmd/server         # http://localhost:4000
```

All seeders are idempotent and safe to repeat. For local work without auth-api, point `AUTH_JWKS_URL`
at a reachable JWKS or use a service key (`INTERNAL_SERVICE_KEY`, `AUTH_ENABLE_API_KEY_AUTH`).

## Changing the schema

1. Edit or add a file in `internal/ent/schema/`.
2. Regenerate the Ent code: `go generate ./internal/ent`.
3. Create the Atlas migration for the change in `internal/ent/migrate/migrations` and refresh
   `atlas.sum` (see `scripts/atlashash`). Never edit an applied migration.
4. Run `go run ./cmd/migrate` against a scratch database to prove it applies.

## Adding a feature

1. A package under `internal/modules/<name>` holding the service (business logic, tenant filtering).
2. A handler under `internal/http/handlers` that checks the permission code and delegates to the service.
3. Register the route in `cmd/server/main.go`; add any new permission code to `cmd/seed`.
4. Publish events through the outbox in the same transaction as the change.
5. Update `docs/integrations.md` when an event or service contract changes.

## Tests

```bash
go build ./...
go vet ./...
go test ./...
```

Integration tests that need Postgres skip themselves unless `ERP_TEST_DATABASE_URL` is set; each run
uses a throwaway schema.

## Troubleshooting

| Symptom | Check |
|---|---|
| `migrate` cannot connect | `POSTGRES_MIGRATE_URL` (or `DB_HOST`, `DB_USER`, `DB_PASSWORD`, `DB_NAME`) |
| Tables not found | the service pins `search_path` to schema `erp`; run `cmd/migrate` first |
| 401 on every call | JWKS URL, issuer and audience must match the token; see `AUTH_*` settings |
| Events not flowing | `EVENTS_ENABLED`, `EVENTS_NATS_URL`, and pending rows in `outbox_events` |
| Payroll numbers look wrong | run `cmd/seed-payroll`; tenants without their own formula inherit the system tenant's |
