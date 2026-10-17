# Contributing to erp-api

Be respectful and professional. Harassment and discrimination are not tolerated.

## Reporting a bug

Give a clear title, the exact steps to reproduce, what you saw, what you expected, and your environment
(OS, Go version, service version or commit).

## Suggesting an enhancement

Describe the change, why it is useful, and any similar behaviour in other platform services.

## Pull requests

1. Branch from `main`: `git checkout -b feat/short-description`.
2. Keep the change focused; one concern per pull request.
3. Before pushing run `go build ./...`, `go vet ./...` and `go test ./...`, and format with `gofmt`.
4. Commit messages use conventional prefixes (`feat`, `fix`, `refactor`, `docs`, `test`, `chore`).
5. Describe what changed and why, and link the issue.

## Code conventions

- Follow the layout in [docs/architecture.md](docs/architecture.md): business logic in
  `internal/modules/<name>`, thin handlers in `internal/http/handlers`.
- Every tenant-scoped query filters by the tenant from the claims. Never trust a tenant id from the body.
- Money is a decimal, never a float. Round through the shared `httpware/money` package; do not add a
  private rounding helper.
- Schema changes go through Ent plus an Atlas migration. Never edit an applied migration.
- Events go through the outbox in the same transaction as the change.
- Prefer reusing the shared libraries (`httpware`, `shared-events`, `shared-service-client`,
  `pagination`, `cache`) over local copies.
- Comments explain why, not what. No secrets in code, config or docs.

## Tests

Add tests with the change. Table-driven unit tests for logic; Postgres integration tests skip unless
`ERP_TEST_DATABASE_URL` is set.
