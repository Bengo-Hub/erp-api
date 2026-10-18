# syntax=docker/dockerfile:1

FROM golang:1.26-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN GOTOOLCHAIN=auto go mod download
COPY . .
RUN GOTOOLCHAIN=auto CGO_ENABLED=0 go build -o /out/erp-api ./cmd/server
# Migration + RBAC seed entrypoints (idempotent; invoked as one-off Jobs by build.sh).
RUN GOTOOLCHAIN=auto CGO_ENABLED=0 go build -o /out/erp-migrate ./cmd/migrate
RUN GOTOOLCHAIN=auto CGO_ENABLED=0 go build -o /out/erp-seed ./cmd/seed
RUN GOTOOLCHAIN=auto CGO_ENABLED=0 go build -o /out/erp-seed-payroll ./cmd/seed-payroll
RUN GOTOOLCHAIN=auto CGO_ENABLED=0 go build -o /out/erp-seed-defaults ./cmd/seed-defaults
RUN GOTOOLCHAIN=auto CGO_ENABLED=0 go build -o /out/erp-sync-employees ./cmd/sync-employees

FROM alpine:3.20
RUN apk add --no-cache ca-certificates
RUN addgroup -S app && adduser -S app -G app
WORKDIR /app
COPY --from=builder /out/erp-api /usr/local/bin/erp-api
COPY --from=builder /out/erp-migrate /usr/local/bin/erp-migrate
COPY --from=builder /out/erp-seed /usr/local/bin/erp-seed
COPY --from=builder /out/erp-seed-payroll /usr/local/bin/erp-seed-payroll
COPY --from=builder /out/erp-seed-defaults /usr/local/bin/erp-seed-defaults
COPY --from=builder /out/erp-sync-employees /usr/local/bin/erp-sync-employees
# Entrypoint script: run migrate + seed (idempotent), then start the server — same pattern as
# inventory-api/pos-api/logistics-api/subscriptions-api.
COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh
USER app
EXPOSE 4000
ENV HTTP_PORT=4000
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
