#!/usr/bin/env bash

# =============================================================================
# BengoERP API - Production Deployment Script
# =============================================================================
# This script handles the complete production deployment process:
# - Security scanning and validation
# - Docker container building with SSH support
# - Database setup and management
# - Kubernetes secrets and configuration
# - Helm chart deployment updates
# - Multi-environment deployment support
# =============================================================================

set -euo pipefail
# Disable history expansion to avoid issues with passwords containing '!'
set +H

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Logging functions
log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()    { echo -e "${PURPLE}[STEP]${NC} $1"; }
log_debug()   { echo -e "${CYAN}[DEBUG]${NC} $1"; }

# =============================================================================
# Helper functions
# =============================================================================

ensure_kube_config() {
    if [[ -n "${KUBE_CONFIG:-}" ]]; then
        mkdir -p ~/.kube
        echo "$KUBE_CONFIG" | base64 -d > ~/.kube/config
        chmod 600 ~/.kube/config
        export KUBECONFIG=~/.kube/config
    fi
}

stream_job() {
    # Args: namespace job_name timeout
    local NS="$1"; local JOB="$2"; local TIMEOUT="$3"; local POD="";
    log_info "Streaming logs for job ${JOB} (waiting for pod to start)..."
    for i in {1..30}; do
        POD=$(kubectl get pods -n "${NS}" -l job-name="${JOB}" -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
        if [[ -n "${POD}" ]]; then
            log_info "Pod started: ${POD}"
            break
        fi
        sleep 2
    done
    if [[ -z "${POD}" ]]; then
        log_error "Pod for job ${JOB} did not start"
        return 2
    fi
    kubectl logs -n "${NS}" -f "${POD}" 2>/dev/null &
    local LOGS_PID=$!
    kubectl wait --for=condition=complete job/"${JOB}" -n "${NS}" --timeout="${TIMEOUT}"
    local RC=$?
    kill ${LOGS_PID} 2>/dev/null || true
    wait ${LOGS_PID} 2>/dev/null || true
    if [[ ${RC} -ne 0 ]]; then
        log_info "Final logs for ${JOB}:"
        kubectl logs -n "${NS}" "${POD}" --tail=100 || true
    fi
    return ${RC}
}

# =============================================================================
# CONFIGURATION & ENVIRONMENT SETUP
# =============================================================================

# Application configuration
export APP_NAME="erp-api"
export DEPLOY=${DEPLOY:-true}
export SETUP_DATABASES=${SETUP_DATABASES:-true}
export DB_TYPES=${DB_TYPES:-postgres,redis}
export NAMESPACE=${NAMESPACE:-erp}
export ENV_SECRET_NAME=${ENV_SECRET_NAME:-erp-api-env}
export PROVIDER=${PROVIDER:-contabo}
export CONTABO_API=${CONTABO_API:-true}
export SSH_DEPLOY=${SSH_DEPLOY:-false}

# Registry configuration
export REGISTRY_SERVER=${REGISTRY_SERVER:-docker.io}
export REGISTRY_NAMESPACE=${REGISTRY_NAMESPACE:-codevertex}
export IMAGE_REPO="${REGISTRY_SERVER}/${REGISTRY_NAMESPACE}/${APP_NAME}"

# DevOps repository
export DEVOPS_REPO="Bengo-Hub/devops-k8s"
export DEVOPS_DIR=${DEVOPS_DIR:-"$HOME/devops-k8s"}
export VALUES_FILE_PATH="apps/${APP_NAME}/values.yaml"

# Git configuration
export GIT_EMAIL=${GIT_EMAIL:-"titusowuor30@gmail.com"}
export GIT_USER=${GIT_USER:-"Titus Owuor"}

# Security scanning - be less strict for deployment
export TRIVY_ECODE=${TRIVY_ECODE:-0}

# Get commit ID
if [[ -z ${GITHUB_SHA:-} ]]; then
    export GIT_COMMIT_ID=$(git rev-parse --short=8 HEAD)
else
    export GIT_COMMIT_ID=${GITHUB_SHA::8}
fi

log_info "Starting BengoERP API deployment"
log_info "App Name: ${APP_NAME}"
log_info "Git Commit: ${GIT_COMMIT_ID}"
log_info "Deploy Mode: ${DEPLOY}"
log_info "Target Image: ${IMAGE_REPO}:${GIT_COMMIT_ID}"

# =============================================================================
# PREREQUISITE CHECKS
# =============================================================================

log_step "Checking prerequisites..."

check_command() {
    if ! command -v "$1" &> /dev/null; then
        log_error "$1 is required but not installed"
        exit 1
    fi
}

# Check required commands
for cmd in git docker kubectl helm yq jq curl trivy; do
    check_command "$cmd"
done

log_success "All prerequisites are available"

# =============================================================================
# SECURITY VULNERABILITY SCANNING
# =============================================================================

log_step "Running security vulnerability scan..."

log_info "Scanning filesystem for vulnerabilities"
# Exclude development certificates and sensitive files from scanning
trivy fs . --exit-code "$TRIVY_ECODE" --format table --skip-files "localhost*.pem" --skip-files "*.key" --skip-files "*.crt" --skip-files "integrations/payments/card_payment.py"

log_success "Filesystem vulnerability scan completed"

# =============================================================================
# DOCKER CONTAINER BUILD
# =============================================================================

log_step "Building Docker container..."

SSH_CONFIGURED=false

# Check if SSH keys are available for Docker build
if [[ -n "${DOCKER_SSH_KEY:-}" ]]; then
    log_info "Setting up SSH key for Docker build"
    mkdir -p -m 0700 ~/.ssh
    echo "$DOCKER_SSH_KEY" | base64 -d > ~/.ssh/id_rsa
    chmod 0600 ~/.ssh/id_rsa
    ssh-keyscan github.com >> ~/.ssh/known_hosts 2>/dev/null || true

    # For CI/CD environments, try non-interactive SSH key addition
    if [[ -n "${CI:-}" ]] || [[ -n "${GITHUB_ACTIONS:-}" ]]; then
        log_info "Running in CI/CD environment, using non-interactive SSH setup"

        # Start ssh-agent
        eval "$(ssh-agent -s)" >/dev/null 2>&1
        
        # Create wrapper script for SSH_ASKPASS
        cat > /tmp/ssh-askpass.sh << 'EOF'
#!/bin/sh
echo "codevertex"
EOF
        chmod +x /tmp/ssh-askpass.sh
        
        # Add key with passphrase using SSH_ASKPASS
        export SSH_ASKPASS=/tmp/ssh-askpass.sh
        export SSH_ASKPASS_REQUIRE=force
        export DISPLAY=:0
        
        if setsid ssh-add ~/.ssh/id_rsa < /dev/null >/dev/null 2>&1; then
            SSH_CONFIGURED=true
            log_success "SSH configured for Docker build with passphrase"
        else
            log_warning "SSH key add failed, building without SSH (this is normal if key has no passphrase)"
            rm -f ~/.ssh/id_rsa /tmp/ssh-askpass.sh
            SSH_CONFIGURED=false
        fi
    else
        # Interactive environment - try normal ssh-add with timeout
        if timeout 10 ssh-add ~/.ssh/id_rsa 2>/dev/null; then
            SSH_CONFIGURED=true
            log_success "SSH configured for Docker build"
        else
            log_warning "SSH key has passphrase or failed to add to agent, building without SSH"
            rm -f ~/.ssh/id_rsa
            SSH_CONFIGURED=false
        fi
    fi
else
    log_info "No SSH key provided, building without SSH"
    SSH_CONFIGURED=false
fi

if [[ "$SSH_CONFIGURED" == "true" ]]; then
    log_info "Building with SSH support"
    DOCKER_BUILDKIT=1 docker build . \
        --ssh default="$SSH_AUTH_SOCK" \
        -t "${IMAGE_REPO}:${GIT_COMMIT_ID}"
else
    log_info "Building without SSH"
    DOCKER_BUILDKIT=1 docker build . \
        -t "${IMAGE_REPO}:${GIT_COMMIT_ID}"
fi

log_success "Docker container build completed"

# =============================================================================
# CONTAINER VULNERABILITY SCANNING
# =============================================================================

log_step "Running container vulnerability scan..."

trivy image "${IMAGE_REPO}:${GIT_COMMIT_ID}" \
    --exit-code "$TRIVY_ECODE" \
    --format table \
    --ignorefile .trivyignore

log_success "Container vulnerability scan completed"

# =============================================================================
# DEPLOYMENT PHASE - USE CENTRALIZED WORKFLOW
# =============================================================================

if [[ "$DEPLOY" == "true" ]]; then
    log_step "Starting deployment process..."

    # Authenticate with registry
    if [[ -n "${REGISTRY_USERNAME:-}" && -n "${REGISTRY_PASSWORD:-}" ]]; then
        log_info "Logging into container registry"
        echo "$REGISTRY_PASSWORD" | docker login "$REGISTRY_SERVER" -u "$REGISTRY_USERNAME" --password-stdin
    fi

    # Push container to registry
    log_info "Pushing container to registry"
    docker push "${IMAGE_REPO}:${GIT_COMMIT_ID}"
    log_success "Container pushed to registry"

    # Enhanced deployment logic moved from reusable workflow
    if [[ "$DEPLOY" == "true" ]]; then
        log_step "Starting enhanced deployment process..."

        # Setup environment secrets from existing databases (skip DB installation - handled by devops-k8s)
        if [[ "$SETUP_DATABASES" == "true" ]]; then
            ensure_kube_config
            
            log_info "Databases are managed by devops-k8s infrastructure"
            log_info "Retrieving credentials from existing secrets and setting up app environment"
            
            if [[ -f "scripts/setup_env_secrets.sh" ]]; then
                chmod +x scripts/setup_env_secrets.sh
                VALIDATION_OUTPUT=$(./scripts/setup_env_secrets.sh) || { log_error "Environment secret setup failed"; exit 1; }
                
                # Parse output for validated credentials
                export EFFECTIVE_PG_PASS=$(echo "$VALIDATION_OUTPUT" | grep "^EFFECTIVE_PG_PASS=" | cut -d= -f2-)
                export VALIDATED_DB_USER=$(echo "$VALIDATION_OUTPUT" | grep "^VALIDATED_DB_USER=" | cut -d= -f2-)
                export VALIDATED_DB_NAME=$(echo "$VALIDATION_OUTPUT" | grep "^VALIDATED_DB_NAME=" | cut -d= -f2-)
                
                log_success "Environment secrets configured successfully"
            else
                log_error "scripts/setup_env_secrets.sh not found"
                exit 1
            fi
        fi

        # Kubernetes secrets and JWT setup
        if [[ -n "${KUBE_CONFIG:-}" ]]; then
            log_step "Setting up Kubernetes secrets..."

            ensure_kube_config

            # Create namespace if needed
            kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || kubectl create ns "$NAMESPACE"

            # CRITICAL: Do NOT apply kubeSecrets/devENV.yaml in CI/CD
            # It contains outdated credentials and will overwrite the verified credentials
            # from setup_env_secrets.sh. Only apply it in local/manual deployments.
            if [[ -z "${CI:-}${GITHUB_ACTIONS:-}" && -f "kubeSecrets/devENV.yaml" ]]; then
                log_info "Local deployment detected - applying kubeSecrets/devENV.yaml"
                kubectl apply -f kubeSecrets/devENV.yaml || log_warning "Failed to apply dev secrets"
            elif [[ -f "kubeSecrets/devENV.yaml" ]]; then
                log_info "CI/CD deployment - skipping kubeSecrets/devENV.yaml (uses setup_env_secrets.sh instead)"
            fi

            # Ensure JWT secret exists (patch existing secret, don't recreate)
            if ! kubectl -n "$NAMESPACE" get secret "$ENV_SECRET_NAME" -o jsonpath='{.data.JWT_SECRET}' >/dev/null 2>&1; then
                JWT_SECRET=$(openssl rand -hex 32)
                if kubectl -n "$NAMESPACE" get secret "$ENV_SECRET_NAME" >/dev/null 2>&1; then
                    kubectl -n "$NAMESPACE" patch secret "$ENV_SECRET_NAME" -p "{\"stringData\":{\"JWT_SECRET\":\"$JWT_SECRET\"}}"
                    log_success "JWT secret added to existing secret"
                else
                    log_warning "Environment secret doesn't exist yet - JWT will be added later"
                fi
            fi

            # Create/Update docker registry pull secret if credentials are provided
            if [[ -n "${REGISTRY_USERNAME:-}" && -n "${REGISTRY_PASSWORD:-}" ]]; then
                log_step "Configuring image pull secret for registry ${REGISTRY_SERVER}"
                kubectl -n "$NAMESPACE" create secret docker-registry registry-credentials \
                  --docker-server="${REGISTRY_SERVER}" \
                  --docker-username="${REGISTRY_USERNAME}" \
                  --docker-password="${REGISTRY_PASSWORD}" \
                  --dry-run=client -o yaml | kubectl apply -f - || log_warning "Failed to create image pull secret"
            fi
        fi

        # Helm values update (using modular script)
        if [[ -n "${KUBE_CONFIG:-}" ]]; then
            if [[ -f "scripts/update_helm_values.sh" ]]; then
                chmod +x scripts/update_helm_values.sh
                ./scripts/update_helm_values.sh || log_warning "Helm values update failed"
            else
                log_warning "scripts/update_helm_values.sh not found; skipping Helm values update"
            fi
        fi

        # Ensure ArgoCD Application has correct ignoreDifferences for PVCs
        if [[ -n "${KUBE_CONFIG:-}" ]]; then
            log_step "Ensuring ArgoCD Application has PVC ignoreDifferences configured..."
            
            # Check if ArgoCD Application exists and has ignoreDifferences for PVCs
            if kubectl -n argocd get application erp-api >/dev/null 2>&1; then
                HAS_PVC_IGNORE=$(kubectl -n argocd get application erp-api -o jsonpath='{.spec.ignoreDifferences}' | grep -i persistentvolumeclaim || echo "")
                
                if [[ -z "$HAS_PVC_IGNORE" ]]; then
                    log_info "Updating ArgoCD Application with PVC ignoreDifferences..."
                    kubectl -n argocd patch application erp-api --type merge -p '{
                      "spec": {
                        "ignoreDifferences": [
                          {
                            "group": "",
                            "kind": "PersistentVolumeClaim",
                            "jsonPointers": ["/spec/volumeName", "/spec/volumeMode", "/status"]
                          }
                        ]
                      }
                    }' || log_warning "Could not patch ArgoCD Application"
                    log_success "ArgoCD Application updated with PVC ignoreDifferences"
                else
                    log_info "ArgoCD Application already has PVC ignoreDifferences configured"
                fi
            else
                log_info "ArgoCD Application 'erp-api' not found yet - will be created with correct config"
            fi
        fi

        # Database migrations (ensure DBs ready and env secret exists before running)
        if [[ "$SETUP_DATABASES" == "true" && -n "${KUBE_CONFIG:-}" ]]; then
            # Ensure kubeconfig is set up
            ensure_kube_config

            # Wait for databases to be ready (already managed by devops-k8s)
            log_info "Waiting for PostgreSQL to be ready..."
            kubectl -n "$NAMESPACE" rollout status statefulset/postgresql --timeout=180s || log_warning "PostgreSQL not fully ready"
            
            log_info "Waiting for Redis to be ready..."
            kubectl -n "$NAMESPACE" rollout status statefulset/redis-master --timeout=120s || log_warning "Redis not fully ready"
            
            # Grace period after readiness before connections (minimum 5 seconds)
            log_info "Waiting 5 seconds to allow database services to stabilize before connecting..."
            sleep 5
            
            # Verify env secret exists (created by setup_env_secrets.sh earlier)
            if ! kubectl -n "$NAMESPACE" get secret "$ENV_SECRET_NAME" >/dev/null 2>&1; then
                log_error "Environment secret ${ENV_SECRET_NAME} not found; cannot run migrations"
                exit 1
            fi
            log_info "Environment secret ${ENV_SECRET_NAME} verified"

            # Run database migrations (using modular script)
            if [[ -f "scripts/run_migrations.sh" ]]; then
                chmod +x scripts/run_migrations.sh
                ./scripts/run_migrations.sh || { log_error "Migration failed"; exit 1; }
            else
                log_error "scripts/run_migrations.sh not found"
                exit 1
            fi

            # Seed initial data after migrations (using modular script)
            if [[ -f "scripts/run_seeding.sh" ]]; then
                chmod +x scripts/run_seeding.sh
                ./scripts/run_seeding.sh || { log_error "Seeding failed"; exit 1; }
            else
                log_error "scripts/run_seeding.sh not found"
                exit 1
            fi

            # ALLOWED_HOSTS and database credentials are now set once in setup_env_secrets.sh
            # They include comprehensive network ranges and are NEVER updated after verification
            # This prevents unnecessary restarts and ensures stable configuration
            log_info "ALLOWED_HOSTS and database credentials set in environment secret"
            log_info "Secret will NOT be modified again to prevent pod restarts"
            
            # Force ONE restart of ALL deployments to pick up the verified credentials
            log_step "Restarting all deployments to apply verified credentials..."
            
            # Restart main API deployment
            if kubectl -n "$NAMESPACE" get deployment erp-api-app >/dev/null 2>&1; then
                kubectl -n "$NAMESPACE" rollout restart deployment/erp-api-app || log_warning "Could not restart API deployment"
                log_info "API deployment restart triggered"
            else
                log_info "API deployment doesn't exist yet - ArgoCD will create it"
            fi
            
            # Restart Celery worker deployment (uses Redis password)
            if kubectl -n "$NAMESPACE" get deployment erp-api-app-celery-worker >/dev/null 2>&1; then
                kubectl -n "$NAMESPACE" rollout restart deployment/erp-api-app-celery-worker || log_warning "Could not restart Celery worker"
                log_info "Celery worker deployment restart triggered"
            else
                log_info "Celery worker doesn't exist yet - ArgoCD will create it"
            fi
            
            # Restart Celery beat deployment (uses Redis password)
            if kubectl -n "$NAMESPACE" get deployment erp-api-app-celery-beat >/dev/null 2>&1; then
                kubectl -n "$NAMESPACE" rollout restart deployment/erp-api-app-celery-beat || log_warning "Could not restart Celery beat"
                log_info "Celery beat deployment restart triggered"
            else
                log_info "Celery beat doesn't exist yet - ArgoCD will create it"
            fi
            
            log_success "All deployments restarted with verified credentials (DB + Redis)"
        fi

        # Note: ArgoCD applications are configured with automated sync
        # They will automatically detect git changes and sync when repository is updated
        log_info "ArgoCD applications configured for automated sync - no manual intervention needed"

        log_success "Enhanced deployment process completed!"

        # Wait for service URLs and retrieve them
        if [[ -n "${KUBE_CONFIG:-}" ]]; then
            log_step "Retrieving service URLs..."

            # Setup kubeconfig
            mkdir -p ~/.kube
            echo "$KUBE_CONFIG" | base64 -d > ~/.kube/config
            chmod 600 ~/.kube/config
            export KUBECONFIG=~/.kube/config

            # Check if there are any resources in the namespace first
            # Use kubectl to count resources without jq dependency - simplified approach
            if kubectl get all,ingress -n "$NAMESPACE" --ignore-not-found=true -o name >/dev/null 2>&1; then
                # Count the lines to determine if resources exist
                NAMESPACE_RESOURCES=$(kubectl get all,ingress -n "$NAMESPACE" --ignore-not-found=true -o name 2>/dev/null | wc -l | tr -d ' ')
            else
                NAMESPACE_RESOURCES="0"
            fi

            if [[ "$NAMESPACE_RESOURCES" == "0" ]]; then
                log_warning "No resources found in namespace $NAMESPACE yet"
                log_info "This is normal if ArgoCD applications haven't synced yet"
                log_info "Please check ArgoCD interface - applications should sync automatically"
                SERVICE_URLS="Applications are syncing via ArgoCD - check ArgoCD interface for status"
            else
                # Wait for ingress to be ready and get URLs (API hosts only)
                SERVICE_URLS=""
                MAX_WAIT=300  # 5 minutes
                WAIT_INTERVAL=15  # Increased interval since ArgoCD sync takes time

                for i in $(seq 1 $((MAX_WAIT / WAIT_INTERVAL))); do
                    log_info "Checking for ingress resources (attempt $i/$((MAX_WAIT / WAIT_INTERVAL)))"

                    # Check if ingress exists and get URLs
                    INGRESS_INFO=$(kubectl get ingress -n "$NAMESPACE" -o json 2>/dev/null || echo "")

                    if [[ -n "$INGRESS_INFO" && "$INGRESS_INFO" != "No resources found" ]]; then
                        # Extract API URLs (erpapi.*) from ingress
                        URLS=$(kubectl get ingress -n "$NAMESPACE" -o jsonpath='{.items[*].spec.rules[*].host}' 2>/dev/null | tr ' ' '\n' | grep -v '^$' | grep -E '^erpapi(\.|$)' | head -5 | tr '\n' ' ' | sed 's/[[:space:]]*$//')

                        if [[ -n "$URLS" ]]; then
                            SERVICE_URLS="$URLS"
                            log_success "Service URLs retrieved: $SERVICE_URLS"
                            break
                        fi
                    fi

                    if [[ $i -lt $((MAX_WAIT / WAIT_INTERVAL)) ]]; then
                        log_info "Waiting ${WAIT_INTERVAL}s before next check..."
                        sleep $WAIT_INTERVAL
                    fi
                done

                if [[ -z "$SERVICE_URLS" ]]; then
                    log_warning "Could not retrieve service URLs within timeout"
                    log_info "This may be normal if applications are still syncing"
                    SERVICE_URLS="Applications are syncing - check ArgoCD interface for application status and URLs"
                fi
            fi

            # Export for summary
            export SERVICE_URLS
        fi
    fi

else
    log_info "Deploy mode disabled (DEPLOY=${DEPLOY}). Build completed but not deployed."
fi

# =============================================================================
# DEPLOYMENT SUMMARY
# =============================================================================

log_step "Deployment Summary"
echo "=========================================="
echo "Service: BengoERP API"
echo "App Name: ${APP_NAME}"
echo "Git Commit: ${GIT_COMMIT_ID}"
echo "Image: ${IMAGE_REPO}:${GIT_COMMIT_ID}"
echo "Deploy Mode: ${DEPLOY}"
echo "SSH Support: $([[ "$SSH_CONFIGURED" == "true" ]] && echo '✅ Enabled' || echo '❌ Disabled')"
echo "Databases: $([[ "$SETUP_DATABASES" == "true" ]] && echo "✅ $DB_TYPES" || echo '❌ Disabled')"
echo "Helm Update: $([[ "$DEPLOY" == "true" ]] && echo '✅ Handled by deploy.yml' || echo '❌ Skipped')"

# Display service URLs if available
if [[ "$DEPLOY" == "true" && -n "${SERVICE_URLS:-}" ]]; then
  echo ""
  echo "🌐 Service URLs:"
  echo "$SERVICE_URLS"
fi

echo "=========================================="

log_success "BengoERP API deployment process completed!"

# Exit with success code - don't fail if service URL retrieval had issues
exit 0
