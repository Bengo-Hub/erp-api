#!/usr/bin/env bash
# Environment secret update script
# Updates erp-api-env secret with validated DB credentials and production config

set -euo pipefail
set +H

log_info() { echo -e "\033[0;34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[0;32m[SUCCESS]\033[0m $1"; }
log_warning() { echo -e "\033[1;33m[WARNING]\033[0m $1"; }

# Required variables
NAMESPACE=${NAMESPACE:-erp}
ENV_SECRET_NAME=${ENV_SECRET_NAME:-erp-api-env}
APP_DB_USER=${VALIDATED_DB_USER:-${APP_DB_USER:-erp_user}}
APP_DB_NAME=${VALIDATED_DB_NAME:-${PG_DATABASE:-bengo_erp}}
EFFECTIVE_PG_PASS=${EFFECTIVE_PG_PASS:-}

if [[ -z "$EFFECTIVE_PG_PASS" ]]; then
    log_warning "EFFECTIVE_PG_PASS not set; skipping env secret update"
    exit 0
fi

log_info "Updating ${ENV_SECRET_NAME} with validated credentials and production config..."

SECRET_ARGS=(
  --from-literal=DATABASE_URL="postgresql://${APP_DB_USER}:${EFFECTIVE_PG_PASS}@postgresql.${NAMESPACE}.svc.cluster.local:5432/${APP_DB_NAME}"
  --from-literal=DB_HOST="postgresql.${NAMESPACE}.svc.cluster.local"
  --from-literal=DB_PORT="5432"
  --from-literal=DB_NAME="${APP_DB_NAME}"
  --from-literal=DB_USER="${APP_DB_USER}"
  --from-literal=DB_PASSWORD="${EFFECTIVE_PG_PASS}"
)

# Add Redis credentials
REDIS_PASS=$(kubectl -n "$NAMESPACE" get secret redis -o jsonpath='{.data.redis-password}' 2>/dev/null | base64 -d || true)
if [[ -z "$REDIS_PASS" && -n "${REDIS_PASSWORD:-}" ]]; then
    REDIS_PASS="$REDIS_PASSWORD"
fi
if [[ -n "$REDIS_PASS" ]]; then
  SECRET_ARGS+=(--from-literal=REDIS_URL="redis://:${REDIS_PASS}@redis-master.${NAMESPACE}.svc.cluster.local:6379/0")
  SECRET_ARGS+=(--from-literal=CELERY_BROKER_URL="redis://:${REDIS_PASS}@redis-master.${NAMESPACE}.svc.cluster.local:6379/0")
  SECRET_ARGS+=(--from-literal=CELERY_RESULT_BACKEND="redis://:${REDIS_PASS}@redis-master.${NAMESPACE}.svc.cluster.local:6379/1")
  SECRET_ARGS+=(--from-literal=REDIS_HOST="redis-master.${NAMESPACE}.svc.cluster.local")
  SECRET_ARGS+=(--from-literal=REDIS_PORT="6379")
  SECRET_ARGS+=(--from-literal=REDIS_PASSWORD="${REDIS_PASS}")
fi

# Add Django and application secrets from environment
if [[ -n "${DJANGO_SECRET_KEY:-}" ]]; then
  SECRET_ARGS+=(--from-literal=DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY}")
  SECRET_ARGS+=(--from-literal=SECRET_KEY="${DJANGO_SECRET_KEY}")
fi

# Production Django settings
SECRET_ARGS+=(--from-literal=DJANGO_SETTINGS_MODULE="ProcureProKEAPI.settings")
SECRET_ARGS+=(--from-literal=DEBUG="False")
SECRET_ARGS+=(--from-literal=DJANGO_ENV="production")
# NOTE: Django doesn't support CIDR notation, use wildcards for private IP ranges
# CRITICAL: This allows health checks from any pod/node in the cluster
SECRET_ARGS+=(--from-literal=ALLOWED_HOSTS="erpapi.masterspace.co.ke,erp.masterspace.co.ke,localhost,127.0.0.1,*.masterspace.co.ke,10.*,172.*,192.168.*")

# CORS and Frontend
SECRET_ARGS+=(--from-literal=CORS_ALLOWED_ORIGINS="https://erp.masterspace.co.ke,http://localhost:3000,*.masterspace.co.ke")
SECRET_ARGS+=(--from-literal=FRONTEND_URL="https://erp.masterspace.co.ke")
SECRET_ARGS+=(--from-literal=CSRF_TRUSTED_ORIGINS="https://erp.masterspace.co.ke,https://erpapi.masterspace.co.ke")

# Media and static file configuration
SECRET_ARGS+=(--from-literal=MEDIA_ROOT="/app/media")
SECRET_ARGS+=(--from-literal=MEDIA_URL="/media/")
SECRET_ARGS+=(--from-literal=STATIC_ROOT="/app/staticfiles")
SECRET_ARGS+=(--from-literal=STATIC_URL="/static/")

# Channels/ASGI configuration for WebSockets in production
# Use Redis for channel layer
SECRET_ARGS+=(--from-literal=CHANNEL_BACKEND="channels_redis.core.RedisChannelLayer")
SECRET_ARGS+=(--from-literal=CHANNEL_URL="redis://:${REDIS_PASS:-${REDIS_PASSWORD:-}}@redis-master.${NAMESPACE}.svc.cluster.local:6379/2")

# Email configuration (if provided)
if [[ -n "${EMAIL_HOST_USER:-}" ]]; then
  SECRET_ARGS+=(--from-literal=EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend")
  SECRET_ARGS+=(--from-literal=EMAIL_HOST="${EMAIL_HOST:-smtp.gmail.com}")
  SECRET_ARGS+=(--from-literal=EMAIL_PORT="${EMAIL_PORT:-587}")
  SECRET_ARGS+=(--from-literal=EMAIL_USE_TLS="True")
  SECRET_ARGS+=(--from-literal=EMAIL_HOST_USER="${EMAIL_HOST_USER}")
  SECRET_ARGS+=(--from-literal=EMAIL_HOST_PASSWORD="${EMAIL_HOST_PASSWORD:-}")
  SECRET_ARGS+=(--from-literal=DEFAULT_FROM_EMAIL="${EMAIL_HOST_USER}")
fi

kubectl -n "$NAMESPACE" create secret generic "$ENV_SECRET_NAME" "${SECRET_ARGS[@]}" \
  --dry-run=client -o yaml | kubectl apply -f - || { log_error "Failed to update env secret"; exit 1; }

log_success "Environment secret refreshed with validated credentials and production config"

