# syntax=docker/dockerfile:1

FROM golang:1.26-alpine AS builder
WORKDIR /src
COPY go.mod go.sum ./
RUN GOTOOLCHAIN=auto go mod download
COPY . .
RUN GOTOOLCHAIN=auto CGO_ENABLED=0 go build -o /out/erp-api ./cmd/server

FROM alpine:3.20
RUN addgroup -S app && adduser -S app -G app
WORKDIR /app
COPY --from=builder /out/erp-api /usr/local/bin/erp-api
USER app
EXPOSE 4000
ENV HTTP_PORT=4000
ENTRYPOINT ["/usr/local/bin/erp-api"]
