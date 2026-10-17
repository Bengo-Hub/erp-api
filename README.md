# erp-api

The HR and internal-ops service of the Codevertex platform, written in Go. It owns employees, payroll,
leave, attendance, appraisals, performance, recruitment, training, approvals, business config, a task
tracker and FX rates. Money, stock, CRM, orders and POS live in other services; see
[docs/architecture.md](docs/architecture.md).

- Go 1.26, Ent ORM, Atlas migrations, PostgreSQL (schema `erp`), Redis, NATS JetStream
- Identity comes from auth-api (RS256 JWT, JWKS). Payroll money movement goes through treasury-api.
- UI: `erp/erp-ui`

## Quick start

```bash
# set the variables listed in docs/architecture.md section 6 (all have local defaults)
POSTGRES_MIGRATE_URL=postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable go run ./cmd/migrate
POSTGRES_URL=postgres://postgres:postgres@localhost:5432/bengo_erp?sslmode=disable go run ./cmd/seed
go run ./cmd/server           # listens on :4000
```

Probes: `GET /healthz`, `GET /readyz`, `GET /metrics`. The swagger files are in `internal/http/docs`.

More detail: [DEVELOPMENT.md](DEVELOPMENT.md).

## Documentation

| Doc | Content |
|---|---|
| [docs/architecture.md](docs/architecture.md) | stack, layout, request lifecycle, payroll engine, configuration |
| [docs/integrations.md](docs/integrations.md) | events, service to service contracts, subscription gating |
| [docs/erd.md](docs/erd.md) | schema |
| [docs/build-history.md](docs/build-history.md) | what was built and the design rules it settled |
| [docs/backlog.md](docs/backlog.md) | open work and what is done |
| [docs/frontend-rules.md](docs/frontend-rules.md) | rules for erp-ui |
| [docs/kra-statutory-report-templates.md](docs/kra-statutory-report-templates.md), [docs/payroll-tax-updates-2025.md](docs/payroll-tax-updates-2025.md) | statutory payroll references |

## Build and deploy

`Dockerfile` builds the binaries and `scripts/entrypoint.sh` migrates, seeds and starts the server.
`build.sh` and `.github/workflows/deploy.yml` build and push the image and update the devops-k8s
values; ArgoCD rolls it out. Kubernetes extras are in [k8s/](k8s).

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).
