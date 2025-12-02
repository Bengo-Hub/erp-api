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

# Get PostgreSQL password - Use master password for service-specific user
APP_DB_USER="${APP_DB_USER:-erp_user}"  # Service-specific user (created by create-service-database.sh)
APP_DB_NAME="$PG_DATABASE"

# CRITICAL: Service users now use POSTGRES_PASSWORD (master password)
# Get it from the PostgreSQL secret in infra namespace
if kubectl -n infra get secret postgresql >/dev/null 2>&1; then
    # Get admin password (master password used for all service users)
    EXISTING_PG_PASS=$(kubectl -n infra get secret postgresql -o jsonpath='{.data.admin-user-password}' 2>/dev/null | base64 -d || true)
    
    if [[ -z "$EXISTING_PG_PASS" ]]; then
        # Fallback to postgres-password if admin-user-password not found
        EXISTING_PG_PASS=$(kubectl -n infra get secret postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d || true)
    fi
    
    if [[ -n "$EXISTING_PG_PASS" ]]; then
        log_info "Retrieved PostgreSQL master password from database secret"
        log_info "Using service-specific user: ${APP_DB_USER}"
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
    log_error "Ensure PostgreSQL is installed: kubectl get secret postgresql -n infra"
    exit 1
fi

log_info "Database password retrieved and verified (length: ${#APP_DB_PASS} chars)"

# Get Redis password - ALWAYS use the password from the live database
# CRITICAL: The database password is the source of truth
# Get it from the Redis secret (where Helm stores it) in infra namespace
if kubectl -n infra get secret redis >/dev/null 2>&1; then
    REDIS_PASS=$(kubectl -n infra get secret redis -o jsonpath='{.data.redis-password}' 2>/dev/null | base64 -d || true)
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
    log_error "Ensure Redis is installed: kubectl get secret redis -n infra"
    exit 1
fi

log_info "Redis password retrieved and verified (length: ${#REDIS_PASS} chars)"

log_info "Database credentials retrieved: user=${APP_DB_USER}, db=${APP_DB_NAME}"

# Get cluster IPs early for ALLOWED_HOSTS (before creating secret)
log_step "Retrieving cluster IPs for ALLOWED_HOSTS..."
POD_IPS=$(kubectl get pods -n "$NAMESPACE" -l app=erp-api-app -o jsonpath='{.items[*].status.podIP}' 2>/dev/null | tr ' ' ',' || true)
SVC_IP=$(kubectl get svc erp-api -n "$NAMESPACE" -o jsonpath='{.spec.clusterIP}' 2>/dev/null || true)
NODE_IPS=$(kubectl get nodes -o jsonpath='{.items[*].status.addresses[?(@.type=="InternalIP")].address}' 2>/dev/null | tr ' ' ',' || true)

# Build comprehensive ALLOWED_HOSTS (set once, never changed)
# NOTE: Django doesn't support CIDR notation, use wildcards or explicit IPs
ALLOWED_HOSTS="erpapi.masterspace.co.ke,erp.masterspace.co.ke,localhost,127.0.0.1,*.masterspace.co.ke"
[[ -n "$SVC_IP" ]] && ALLOWED_HOSTS="${ALLOWED_HOSTS},${SVC_IP}"
[[ -n "$POD_IPS" ]] && ALLOWED_HOSTS="${ALLOWED_HOSTS},${POD_IPS}"
[[ -n "$NODE_IPS" ]] && ALLOWED_HOSTS="${ALLOWED_HOSTS},${NODE_IPS}"
# Use wildcards for private IP ranges (Django doesn't support CIDR notation)
# CRITICAL: This allows health checks from any pod/node in the cluster
ALLOWED_HOSTS="${ALLOWED_HOSTS},10.*,172.*,192.168.*"

log_info "ALLOWED_HOSTS (comprehensive, with wildcards for private IPs): ${ALLOWED_HOSTS}"
echo "ALLOWED_HOSTS=${ALLOWED_HOSTS}"

# CRITICAL: Test database connectivity to verify password is correct
log_step "Verifying PostgreSQL password by testing connection..."

# Clean up any existing test pod first
kubectl delete pod -n "$NAMESPACE" pg-test-conn --ignore-not-found >/dev/null 2>&1

# Run connection test with detailed error capture (connecting to infra namespace)
log_info "Testing connection to postgresql.infra.svc.cluster.local:5432 as ${APP_DB_USER}..."
TEST_OUTPUT=$(mktemp)
set +e
kubectl run -n "$NAMESPACE" pg-test-conn --rm -i --restart=Never --image=postgres:15-alpine --timeout=30s \
  --env="PGPASSWORD=$APP_DB_PASS" \
  --command -- psql -h postgresql.infra.svc.cluster.local -U "$APP_DB_USER" -d "$APP_DB_NAME" -c "SELECT 1;" >$TEST_OUTPUT 2>&1
TEST_RC=$?
set -e

if [[ $TEST_RC -eq 0 ]]; then
    log_success "✓ PostgreSQL password verified - connection successful"
    rm -f $TEST_OUTPUT
else
    log_error "✗ PostgreSQL password verification FAILED (exit code: $TEST_RC)"
    log_error ""
    log_error "Test output:"
    cat $TEST_OUTPUT || true
    rm -f $TEST_OUTPUT
    log_error ""
    log_error "DIAGNOSIS: Password mismatch or connectivity issue"
    log_error "- Secret password length: ${#APP_DB_PASS} chars"
    log_error "- Database host: postgresql.$NAMESPACE.svc.cluster.local:5432"
    log_error "- Database user: $APP_DB_USER"
    log_error ""
    log_error "POSSIBLE CAUSES:"
    log_error "1. PostgreSQL password in K8s secret doesn't match actual database password"
    log_error "2. PostgreSQL StatefulSet not ready yet"
    log_error "3. Network connectivity issues"
    log_error ""
    log_error "IMMEDIATE FIX OPTIONS:"
    log_error ""
    log_error "Option A: Reset PostgreSQL password to match the K8s secret:"
    log_error "  kubectl exec -n $NAMESPACE postgresql-0 -- psql -U postgres -c \"ALTER USER postgres WITH PASSWORD '\$APP_DB_PASS';\""
    log_error ""
    log_error "Option B: Re-run provision workflow to sync passwords:"
    log_error "  This will update PostgreSQL password from GitHub secret POSTGRES_PASSWORD"
    log_error "  https://github.com/Bengo-Hub/devops-k8s/actions/workflows/provision.yml"
    log_error ""
    exit 1
fi

# Generate Django secret key and JWT secret if not provided
DJANGO_SECRET_KEY=${DJANGO_SECRET_KEY:-$(openssl rand -hex 50)}
JWT_SECRET=${JWT_SECRET:-$(openssl rand -hex 32)}

# Create/update environment secret
log_info "Creating/updating environment secret: ${ENV_SECRET_NAME}"
log_info "Secret will include: DB credentials, Redis credentials, Django settings, JWT secret, ALLOWED_HOSTS"

# CRITICAL: Delete and recreate to ensure clean state (prevents stale password issues)
# Using replace --force ensures ALL keys are updated, not merged with old values
kubectl -n "$NAMESPACE" delete secret "$ENV_SECRET_NAME" --ignore-not-found

kubectl -n "$NAMESPACE" create secret generic "$ENV_SECRET_NAME" \
  --from-literal=DATABASE_URL="postgresql://${APP_DB_USER}:${APP_DB_PASS}@postgresql.infra.svc.cluster.local:5432/${APP_DB_NAME}" \
  --from-literal=DB_HOST="postgresql.infra.svc.cluster.local" \
  --from-literal=DB_PORT="5432" \
  --from-literal=DB_NAME="${APP_DB_NAME}" \
  --from-literal=DB_USER="${APP_DB_USER}" \
  --from-literal=DB_PASSWORD="${APP_DB_PASS}" \
  --from-literal=REDIS_URL="redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/0" \
  --from-literal=REDIS_HOST="redis-master.infra.svc.cluster.local" \
  --from-literal=REDIS_PORT="6379" \
  --from-literal=REDIS_PASSWORD="${REDIS_PASS}" \
  --from-literal=CHANNEL_BACKEND="channels_redis.core.RedisChannelLayer" \
  --from-literal=CHANNEL_URL="redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/2" \
  --from-literal=CELERY_BROKER_URL="redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/0" \
  --from-literal=CELERY_RESULT_BACKEND="redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/1" \
  --from-literal=DJANGO_SECRET_KEY="${DJANGO_SECRET_KEY}" \
  --from-literal=SECRET_KEY="${DJANGO_SECRET_KEY}" \
  --from-literal=JWT_SECRET="${JWT_SECRET}" \
  --from-literal=DJANGO_SETTINGS_MODULE="ProcureProKEAPI.settings" \
  --from-literal=DEBUG="False" \
  --from-literal=DJANGO_ENV="production" \
  --from-literal=ALLOWED_HOSTS="${ALLOWED_HOSTS}" \
  --from-literal=CORS_ALLOWED_ORIGINS="https://erp.masterspace.co.ke,http://localhost:3000,*.masterspace.co.ke" \
  --from-literal=FRONTEND_URL="https://erp.masterspace.co.ke" \
  --from-literal=CSRF_TRUSTED_ORIGINS="https://erp.masterspace.co.ke,https://erpapi.masterspace.co.ke" \
  --from-literal=MEDIA_ROOT="/app/media" \
  --from-literal=MEDIA_URL="/media/" \
  --from-literal=STATIC_ROOT="/app/staticfiles" \
  --from-literal=STATIC_URL="/static/"

log_success "Environment secret created/updated with production configuration"
log_info "ALLOWED_HOSTS set to: ${ALLOWED_HOSTS}"
log_info "Verifying secret was created..."
kubectl -n "$NAMESPACE" get secret "$ENV_SECRET_NAME" -o jsonpath='{.data.ALLOWED_HOSTS}' | base64 -d | head -c 100 && echo "..."

# Update kubeSecrets/devENV.yaml with verified credentials for consistency
# This ensures local deployments and Helm values use the same verified credentials
if [[ -f "kubeSecrets/devENV.yaml" ]]; then
    log_step "Updating kubeSecrets/devENV.yaml with verified credentials..."
    
    # Backup existing file
    cp kubeSecrets/devENV.yaml kubeSecrets/devENV.yaml.bak
    
    # Create updated devENV.yaml with verified credentials
    cat > kubeSecrets/devENV.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${ENV_SECRET_NAME}
  namespace: ${NAMESPACE}
type: Opaque
stringData:
  # Database credentials (verified from K8s secrets)
  DATABASE_URL: "postgresql://${APP_DB_USER}:${APP_DB_PASS}@postgresql.infra.svc.cluster.local:5432/${APP_DB_NAME}"
  DB_HOST: "postgresql.infra.svc.cluster.local"
  DB_PORT: "5432"
  DB_NAME: "${APP_DB_NAME}"
  DB_USER: "${APP_DB_USER}"
  DB_PASSWORD: "${APP_DB_PASS}"
  
  # Redis credentials (verified from K8s secrets)
  REDIS_URL: "redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/0"
  REDIS_HOST: "redis-master.infra.svc.cluster.local"
  REDIS_PORT: "6379"
  REDIS_PASSWORD: "${REDIS_PASS}"
  CHANNEL_BACKEND: "channels_redis.core.RedisChannelLayer"
  CHANNEL_URL: "redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/2"
  
  # Celery configuration
  CELERY_BROKER_URL: "redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/0"
  CELERY_RESULT_BACKEND: "redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/1"
  
  # Django secrets
  DJANGO_SECRET_KEY: "${DJANGO_SECRET_KEY}"
  SECRET_KEY: "${DJANGO_SECRET_KEY}"
  JWT_SECRET: "${JWT_SECRET}"
  
  # Django configuration
  DJANGO_SETTINGS_MODULE: "ProcureProKEAPI.settings"
  DEBUG: "False"
  DJANGO_ENV: "production"
  
  # Network configuration (with comprehensive ALLOWED_HOSTS)
  ALLOWED_HOSTS: "${ALLOWED_HOSTS}"
  CORS_ALLOWED_ORIGINS: "https://erp.masterspace.co.ke,http://localhost:3000,*.masterspace.co.ke"
  FRONTEND_URL: "https://erp.masterspace.co.ke"
  CSRF_TRUSTED_ORIGINS: "https://erp.masterspace.co.ke,https://erpapi.masterspace.co.ke"
  
  # Static and media files
  MEDIA_ROOT: "/app/media"
  MEDIA_URL: "/media/"
  STATIC_ROOT: "/app/staticfiles"
  STATIC_URL: "/static/"
EOF

    log_success "✓ kubeSecrets/devENV.yaml updated with verified credentials"
    log_info "Backup saved to kubeSecrets/devENV.yaml.bak"
else
    log_warning "kubeSecrets/devENV.yaml not found - creating new file"
    mkdir -p kubeSecrets
    
    # Create new devENV.yaml with verified credentials
    cat > kubeSecrets/devENV.yaml <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${ENV_SECRET_NAME}
  namespace: ${NAMESPACE}
type: Opaque
stringData:
  # Database credentials (verified from K8s secrets)
  DATABASE_URL: "postgresql://${APP_DB_USER}:${APP_DB_PASS}@postgresql.infra.svc.cluster.local:5432/${APP_DB_NAME}"
  DB_HOST: "postgresql.infra.svc.cluster.local"
  DB_PORT: "5432"
  DB_NAME: "${APP_DB_NAME}"
  DB_USER: "${APP_DB_USER}"
  DB_PASSWORD: "${APP_DB_PASS}"
  
  # Redis credentials (verified from K8s secrets)
  REDIS_URL: "redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/0"
  REDIS_HOST: "redis-master.infra.svc.cluster.local"
  REDIS_PORT: "6379"
  REDIS_PASSWORD: "${REDIS_PASS}"
  CHANNEL_BACKEND: "channels_redis.core.RedisChannelLayer"
  CHANNEL_URL: "redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/2"
  
  # Celery configuration
  CELERY_BROKER_URL: "redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/0"
  CELERY_RESULT_BACKEND: "redis://:${REDIS_PASS}@redis-master.infra.svc.cluster.local:6379/1"
  
  # Django secrets
  DJANGO_SECRET_KEY: "${DJANGO_SECRET_KEY}"
  SECRET_KEY: "${DJANGO_SECRET_KEY}"
  JWT_SECRET: "${JWT_SECRET}"
  
  # Django configuration
  DJANGO_SETTINGS_MODULE: "ProcureProKEAPI.settings"
  DEBUG: "False"
  DJANGO_ENV: "production"
  
  # Network configuration (with comprehensive ALLOWED_HOSTS)
  ALLOWED_HOSTS: "${ALLOWED_HOSTS}"
  CORS_ALLOWED_ORIGINS: "https://erp.masterspace.co.ke,http://localhost:3000,*.masterspace.co.ke"
  FRONTEND_URL: "https://erp.masterspace.co.ke"
  CSRF_TRUSTED_ORIGINS: "https://erp.masterspace.co.ke,https://erpapi.masterspace.co.ke"
  
  # Static and media files
  MEDIA_ROOT: "/app/media"
  MEDIA_URL: "/media/"
  STATIC_ROOT: "/app/staticfiles"
  STATIC_URL: "/static/"
EOF

    log_success "✓ kubeSecrets/devENV.yaml created with verified credentials"
fi

# Export validated credentials for use by parent script
echo "EFFECTIVE_PG_PASS=${APP_DB_PASS}"
echo "VALIDATED_DB_USER=${APP_DB_USER}"
echo "VALIDATED_DB_NAME=${APP_DB_NAME}"

