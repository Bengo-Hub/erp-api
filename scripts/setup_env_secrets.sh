#!/usr/bin/env bash
# Environment secret setup script for BengoERP API
# Retrieves DB credentials from existing Helm releases and creates app env secret

set -euo pipefail
set +H

# Inherit logging functions from parent script or define minimal ones
log_info() { echo -e "\033[0;34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[0;32m[SUCCESS]\033[0m $1"; }
log_warning() { echo -e "\033[1;33m[WARNING]\033[0m $1"; }
log_error() { echo -e "\033[0;31m[ERROR]\033[0m $1"; }
log_step() { echo -e "\033[0;35m[STEP]\033[0m $1"; }

# Required environment variables
NAMESPACE=${NAMESPACE:-erp}
ENV_SECRET_NAME=${ENV_SECRET_NAME:-erp-api-env}
PG_DATABASE=${PG_DATABASE:-bengo_erp}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-}
REDIS_PASSWORD=${REDIS_PASSWORD:-}

log_step "Setting up environment secrets..."

# Ensure kubectl is available
if ! command -v kubectl &> /dev/null; then
    log_error "kubectl is required"
    exit 1
fi

# Get PostgreSQL password from secret or environment
APP_DB_USER="postgres"
APP_DB_NAME="$PG_DATABASE"

# Try to get password from existing PostgreSQL secret
if kubectl -n "$NAMESPACE" get secret postgresql >/dev/null 2>&1; then
    EXISTING_PG_PASS=$(kubectl -n "$NAMESPACE" get secret postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d || true)
    if [[ -n "$EXISTING_PG_PASS" ]]; then
        log_info "Retrieved PostgreSQL password from existing secret"
        APP_DB_PASS="$EXISTING_PG_PASS"
    elif [[ -n "$POSTGRES_PASSWORD" ]]; then
        log_info "Using POSTGRES_PASSWORD from environment"
        APP_DB_PASS="$POSTGRES_PASSWORD"
    else
        log_error "Could not retrieve PostgreSQL password from secret or environment"
        exit 1
    fi
else
    log_warning "PostgreSQL secret not found; using POSTGRES_PASSWORD from environment"
    if [[ -z "$POSTGRES_PASSWORD" ]]; then
        log_error "POSTGRES_PASSWORD environment variable is required"
        exit 1
    fi
    APP_DB_PASS="$POSTGRES_PASSWORD"
fi

# Get Redis password from secret or environment
if kubectl -n "$NAMESPACE" get secret redis >/dev/null 2>&1; then
    REDIS_PASS=$(kubectl -n "$NAMESPACE" get secret redis -o jsonpath='{.data.redis-password}' 2>/dev/null | base64 -d || true)
    if [[ -n "$REDIS_PASS" ]]; then
        log_info "Retrieved Redis password from existing secret"
    elif [[ -n "$REDIS_PASSWORD" ]]; then
        log_info "Using REDIS_PASSWORD from environment"
        REDIS_PASS="$REDIS_PASSWORD"
    else
        log_error "Could not retrieve Redis password from secret or environment"
        exit 1
    fi
else
    log_warning "Redis secret not found; using REDIS_PASSWORD from environment"
    if [[ -z "$REDIS_PASSWORD" ]]; then
        log_error "REDIS_PASSWORD environment variable is required"
        exit 1
    fi
    REDIS_PASS="$REDIS_PASSWORD"
fi

log_info "Database credentials retrieved: user=${APP_DB_USER}, db=${APP_DB_NAME}"

# Generate Django secret key if not provided
DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY:-$(openssl rand -hex 50)}

# Create/update environment secret
log_info "Creating/updating environment secret: ${ENV_SECRET_NAME}"

kubectl -n "$NAMESPACE" create secret generic "$ENV_SECRET_NAME" \
  --from-literal=DATABASE_URL="postgresql://${APP_DB_USER}:${APP_DB_PASS}@postgresql.${NAMESPACE}.svc.cluster.local:5432/${APP_DB_NAME}" \
  --from-literal=DB_HOST="postgresql.${NAMESPACE}.svc.cluster.local" \
  --from-literal=DB_PORT="5432" \
  --from-literal=DB_NAME="${APP_DB_NAME}" \
  --from-literal=DB_USER="${APP_DB_USER}" \
  --from-literal=DB_PASSWORD="${APP_DB_PASS}" \
  --from-literal=REDIS_URL="redis://:${REDIS_PASS}@redis-master.${NAMESPACE}.svc.cluster.local:6379/0" \
  --from-literal=REDIS_HOST="redis-master.${NAMESPACE}.svc.cluster.local" \
  --from-literal=REDIS_PORT="6379" \
  --from-literal=REDIS_PASSWORD="${REDIS_PASS}" \
  --from-literal=CELERY_BROKER_URL="redis://:${REDIS_PASS}@redis-master.${NAMESPACE}.svc.cluster.local:6379/0" \
  --from-literal=CELERY_RESULT_BACKEND="redis://:${REDIS_PASS}@redis-master.${NAMESPACE}.svc.cluster.local:6379/1" \
  --from-literal=DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY}" \
  --from-literal=SECRET_KEY="${DJANGO_SECRET_KEY}" \
  --from-literal=DJANGO_SETTINGS_MODULE="ProcureProKEAPI.settings" \
  --from-literal=DEBUG="False" \
  --from-literal=DJANGO_ENV="production" \
  --from-literal=ALLOWED_HOSTS="erpapi.masterspace.co.ke,localhost,127.0.0.1,*.masterspace.co.ke" \
  --from-literal=CORS_ALLOWED_ORIGINS="https://erp.masterspace.co.ke,http://localhost:3000,*.masterspace.co.ke" \
  --from-literal=FRONTEND_URL="https://erp.masterspace.co.ke" \
  --from-literal=CSRF_TRUSTED_ORIGINS="https://erp.masterspace.co.ke,https://erpapi.masterspace.co.ke" \
  --from-literal=MEDIA_ROOT="/app/media" \
  --from-literal=MEDIA_URL="/media/" \
  --from-literal=STATIC_ROOT="/app/staticfiles" \
  --from-literal=STATIC_URL="/static/" \
  --dry-run=client -o yaml | kubectl apply -f -

log_success "Environment secret created/updated with production configuration"

# Export validated credentials for use by parent script
echo "EFFECTIVE_PG_PASS=${APP_DB_PASS}"
echo "VALIDATED_DB_USER=${APP_DB_USER}"
echo "VALIDATED_DB_NAME=${APP_DB_NAME}"

