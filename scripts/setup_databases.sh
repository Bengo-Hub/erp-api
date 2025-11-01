#!/usr/bin/env bash
# Database setup script for BengoERP API
# Sets up PostgreSQL and Redis using Bitnami Helm charts

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
DB_TYPES=${DB_TYPES:-postgres,redis}
POSTGRES_PASSWORD=${POSTGRES_PASSWORD:-}
REDIS_PASSWORD=${REDIS_PASSWORD:-}
PG_DATABASE=${PG_DATABASE:-bengo_erp}

log_step "Setting up databases..."

# Ensure kubectl is available
if ! command -v kubectl &> /dev/null; then
    log_error "kubectl is required for database setup"
    exit 1
fi

# Create namespace if it doesn't exist
kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || kubectl create ns "$NAMESPACE"

# Install Helm repos
helm repo add bitnami https://charts.bitnami.com/bitnami >/dev/null 2>&1 || true
helm repo update >/dev/null 2>&1 || true

# Parse database types
SAVEIFS=$IFS; IFS=','; set -f; types=($DB_TYPES); IFS=$SAVEIFS; set +f

for db in "${types[@]}"; do
    db=$(echo "$db" | xargs)
    case "$db" in
        postgres)
            log_info "Installing PostgreSQL..."
            # Check if PostgreSQL already exists (skip if managed by devops-k8s)
            if helm -n "$NAMESPACE" status postgresql >/dev/null 2>&1; then
                log_info "PostgreSQL already exists and managed by devops-k8s infrastructure"
                log_info "Skipping PostgreSQL installation/upgrade (handled centrally)"
            fi
            ;;
        redis)
            log_info "Checking Redis..."
            # Check if Redis already exists (skip if managed by devops-k8s)
            if helm -n "$NAMESPACE" status redis >/dev/null 2>&1; then
                log_info "Redis already exists and managed by devops-k8s infrastructure"
                log_info "Skipping Redis installation/upgrade (handled centrally)"
            fi
            ;;
        *)
            log_warning "Unknown database type: $db"
            ;;
    esac
done

# Ensure DB & Redis are ready after installation
kubectl -n "$NAMESPACE" rollout status statefulset/postgresql --timeout=180s || true
kubectl -n "$NAMESPACE" rollout status statefulset/redis-master --timeout=120s || true

log_success "Database setup completed"

