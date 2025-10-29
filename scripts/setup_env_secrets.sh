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

# Get PostgreSQL password - ALWAYS use the password from the live database
APP_DB_USER="postgres"
APP_DB_NAME="$PG_DATABASE"

# CRITICAL: The database password is the source of truth
# Get it from the PostgreSQL secret (where Helm stores it)
if kubectl -n "$NAMESPACE" get secret postgresql >/dev/null 2>&1; then
    EXISTING_PG_PASS=$(kubectl -n "$NAMESPACE" get secret postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d || true)
    if [[ -n "$EXISTING_PG_PASS" ]]; then
        log_info "Retrieved PostgreSQL password from database secret (source of truth)"
        APP_DB_PASS="$EXISTING_PG_PASS"
        
        # Verify it matches env var if provided (for validation)
        if [[ -n "$POSTGRES_PASSWORD" && "$POSTGRES_PASSWORD" != "$EXISTING_PG_PASS" ]]; then
            log_warning "POSTGRES_PASSWORD env var differs from database secret"
            log_warning "Using database secret password (must match actual DB)"
        fi
    else
        log_error "Could not retrieve PostgreSQL password from Kubernetes secret"
        exit 1
    fi
else
    log_error "PostgreSQL secret not found in Kubernetes"
    log_error "Ensure PostgreSQL is installed: kubectl get secret postgresql -n $NAMESPACE"
    exit 1
fi

log_info "Database password retrieved and verified (length: ${#APP_DB_PASS} chars)"

# Get Redis password - ALWAYS use the password from the live database
# CRITICAL: The database password is the source of truth
# Get it from the Redis secret (where Helm stores it)
if kubectl -n "$NAMESPACE" get secret redis >/dev/null 2>&1; then
    REDIS_PASS=$(kubectl -n "$NAMESPACE" get secret redis -o jsonpath='{.data.redis-password}' 2>/dev/null | base64 -d || true)
    if [[ -n "$REDIS_PASS" ]]; then
        log_info "Retrieved Redis password from database secret (source of truth)"
        
        # Verify it matches env var if provided (for validation)
        if [[ -n "$REDIS_PASSWORD" && "$REDIS_PASSWORD" != "$REDIS_PASS" ]]; then
            log_warning "REDIS_PASSWORD env var differs from database secret"
            log_warning "Using database secret password (must match actual DB)"
        fi
    else
        log_error "Could not retrieve Redis password from Kubernetes secret"
        exit 1
    fi
else
    log_error "Redis secret not found in Kubernetes"
    log_error "Ensure Redis is installed: kubectl get secret redis -n $NAMESPACE"
    exit 1
fi

log_info "Redis password retrieved and verified (length: ${#REDIS_PASS} chars)"

log_info "Database credentials retrieved: user=${APP_DB_USER}, db=${APP_DB_NAME}"

# CRITICAL: Test database connectivity to verify password is correct
log_step "Verifying PostgreSQL password by testing connection..."
PGPASSWORD="$APP_DB_PASS" kubectl run -n "$NAMESPACE" pg-test-$$ --rm -i --restart=Never --image=postgres:15-alpine --command -- \
  psql -h postgresql."$NAMESPACE".svc.cluster.local -U "$APP_DB_USER" -d postgres -c "SELECT 1;" >/dev/null 2>&1

if [[ $? -eq 0 ]]; then
    log_success "✓ PostgreSQL password verified - connection successful"
else
    log_error "✗ PostgreSQL password verification FAILED"
    log_error "The password in the Kubernetes secret does NOT match the actual database password"
    log_error ""
    log_error "DIAGNOSIS: Password mismatch detected"
    log_error "- Secret password length: ${#APP_DB_PASS} chars"
    log_error "- Database: postgresql.$NAMESPACE.svc.cluster.local:5432"
    log_error ""
    log_error "POSSIBLE CAUSES:"
    log_error "1. PostgreSQL was provisioned with a different password than stored in the secret"
    log_error "2. The secret was manually edited but database wasn't updated"
    log_error "3. Password contains special characters that need escaping"
    log_error ""
    log_error "FIX: You must update the PostgreSQL password to match the secret, or vice versa"
    log_error "Option A: Reset PostgreSQL password to match the secret:"
    log_error "  kubectl exec -n $NAMESPACE postgresql-0 -- psql -U postgres -c \"ALTER USER postgres WITH PASSWORD '$APP_DB_PASS';\""
    log_error ""
    log_error "Option B: Update the secret to match the database (if you know the correct password):"
    log_error "  kubectl -n $NAMESPACE patch secret postgresql --type merge -p '{\"data\":{\"postgres-password\":\"$(echo -n 'CORRECT_PASSWORD' | base64)\"}}'"
    log_error ""
    exit 1
fi

# Generate Django secret key if not provided
DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY:-$(openssl rand -hex 50)}

# Create/update environment secret
log_info "Creating/updating environment secret: ${ENV_SECRET_NAME}"

# CRITICAL: Delete and recreate to ensure clean state (prevents stale password issues)
# Using replace --force ensures ALL keys are updated, not merged with old values
kubectl -n "$NAMESPACE" delete secret "$ENV_SECRET_NAME" --ignore-not-found

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
  --from-literal=STATIC_URL="/static/"

log_success "Environment secret created/updated with production configuration"

# Export validated credentials for use by parent script
echo "EFFECTIVE_PG_PASS=${APP_DB_PASS}"
echo "VALIDATED_DB_USER=${APP_DB_USER}"
echo "VALIDATED_DB_NAME=${APP_DB_NAME}"

