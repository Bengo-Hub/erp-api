# erp-api: instructions for AI assistants

**Project:** Go HR and internal-ops service (employees, payroll, leave, attendance, appraisals,
recruitment, training, approvals, business config). Module `github.com/Bengo-Hub/erp-api`.
**Stack:** Go 1.26, Ent, Atlas, PostgreSQL (schema `erp`), Redis, NATS JetStream.

Read [docs/architecture.md](../docs/architecture.md) first. There is no Python or Django code in this
repository; if you see a reference to one, it is stale and should be removed.

## Rules

- Business logic lives in `internal/modules/<name>`; handlers in `internal/http/handlers` stay thin.
- Every tenant-scoped query filters by the tenant from the JWT claims.
- Money is a decimal, never a float. Round through `github.com/Bengo-Hub/httpware/money`.
- Schema changes: edit `internal/ent/schema`, run `go generate ./internal/ent`, add an Atlas
  migration. Never edit an applied migration.
- Publish events through the outbox in the same transaction as the change.
- Reuse the shared libraries (`httpware`, `shared-events`, `shared-service-client`, `pagination`,
  `cache`) instead of writing local copies. No duplicate or legacy logic.
- Never write secrets, tokens, keys or server details into any tracked file.
- Verify with `go build ./...`, `go vet ./...` and `go test ./...` before committing.
