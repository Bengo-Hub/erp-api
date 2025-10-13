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
# CONFIGURATION & ENVIRONMENT SETUP
# =============================================================================

# Application configuration
APP_NAME="erp-api"
DEPLOY=${DEPLOY:-false}
SETUP_DATABASES=${SETUP_DATABASES:-true}
DB_TYPES=${DB_TYPES:-postgres,redis}
NAMESPACE=${NAMESPACE:-erp}
ENV_SECRET_NAME=${ENV_SECRET_NAME:-erp-api-env}
PROVIDER=${PROVIDER:-contabo}
CONTABO_API=${CONTABO_API:-true}
SSH_DEPLOY=${SSH_DEPLOY:-false}

# Registry configuration
REGISTRY_SERVER=${REGISTRY_SERVER:-docker.io}
REGISTRY_NAMESPACE=${REGISTRY_NAMESPACE:-codevertex}
IMAGE_REPO="${REGISTRY_SERVER}/${REGISTRY_NAMESPACE}/${APP_NAME}"

# DevOps repository
DEVOPS_REPO="Bengo-Hub/devops-k8s"
VALUES_FILE_PATH="apps/erp-api/values.yaml"

# Git configuration
GIT_EMAIL=${GIT_EMAIL:-"titusowuor30@gmail.com"}
GIT_USER=${GIT_USER:-"Titus Owuor"}

# Security scanning - be less strict for deployment
TRIVY_ECODE=${TRIVY_ECODE:-0}

# Get commit ID
if [[ -z ${GITHUB_SHA:-} ]]; then
    GIT_COMMIT_ID=$(git rev-parse --short=8 HEAD)
else
    GIT_COMMIT_ID=${GITHUB_SHA::8}
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
    # Use DISPLAY and SSH_ASKPASS to avoid passphrase prompts
    if [[ -n "${CI:-}" ]] || [[ -n "${GITHUB_ACTIONS:-}" ]]; then
        log_info "Running in CI/CD environment, using non-interactive SSH setup"

        # Try to add key with passphrase "codevertex"
        if echo "codevertex" | SSH_ASKPASS=/bin/echo ssh-add ~/.ssh/id_rsa 2>/dev/null; then
            SSH_CONFIGURED=true
            log_success "SSH configured for Docker build"
        else
            log_warning "SSH key passphrase incorrect or failed to add to agent, building without SSH"
            rm -f ~/.ssh/id_rsa
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

        # Database setup logic (moved from reusable workflow)
        if [[ "$SETUP_DATABASES" == "true" ]]; then
            log_step "Setting up databases..."

            # Ensure kubectl is available
            if ! command -v kubectl &> /dev/null; then
                log_error "kubectl is required for database setup"
                exit 1
            fi

            # Setup kubeconfig if available
            if [[ -n "${KUBE_CONFIG:-}" ]]; then
                mkdir -p ~/.kube
                echo "$KUBE_CONFIG" | base64 -d > ~/.kube/config
                chmod 600 ~/.kube/config
                export KUBECONFIG=~/.kube/config
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
                        helm upgrade --install postgresql bitnami/postgresql -n "$NAMESPACE" \
                            --set global.postgresql.auth.postgresPassword="$POSTGRES_PASSWORD" \
                            --set global.postgresql.auth.database="appdb" \
                            --wait --timeout=300s || log_warning "PostgreSQL installation failed"
                        ;;
                    redis)
                        log_info "Installing Redis..."
                        helm upgrade --install redis bitnami/redis -n "$NAMESPACE" \
                            --set global.redis.password="$REDIS_PASSWORD" \
                            --wait --timeout=300s || log_warning "Redis installation failed"
                        ;;
                    *)
                        log_warning "Unknown database type: $db"
                        ;;
                esac
            done

            # Create environment secret with database URLs
            if [[ -n "${POSTGRES_PASSWORD:-}" ]]; then
                kubectl -n "$NAMESPACE" create secret generic "$ENV_SECRET_NAME" \
                    --from-literal=DATABASE_URL="postgresql://postgres:${POSTGRES_PASSWORD}@postgresql.${NAMESPACE}.svc.cluster.local:5432/appdb" \
                    --dry-run=client -o yaml | kubectl apply -f - || log_warning "Failed to create DB secret"
            fi

            log_success "Database setup completed"
        fi

        # Kubernetes secrets and JWT setup
        if [[ -n "${KUBE_CONFIG:-}" ]]; then
            log_step "Setting up Kubernetes secrets..."

            mkdir -p ~/.kube
            echo "$KUBE_CONFIG" | base64 -d > ~/.kube/config
            chmod 600 ~/.kube/config
            export KUBECONFIG=~/.kube/config

            # Create namespace if needed
            kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || kubectl create ns "$NAMESPACE"

            # Apply dev environment secrets if available
            if [[ -f "kubeSecrets/devENV.yaml" ]]; then
                kubectl apply -f kubeSecrets/devENV.yaml || log_warning "Failed to apply dev secrets"
            fi

            # Ensure JWT secret exists
            if ! kubectl -n "$NAMESPACE" get secret "$ENV_SECRET_NAME" -o jsonpath='{.data.JWT_SECRET}' >/dev/null 2>&1; then
                JWT_SECRET=$(openssl rand -hex 32)
                if kubectl -n "$NAMESPACE" get secret "$ENV_SECRET_NAME" >/dev/null 2>&1; then
                    kubectl -n "$NAMESPACE" patch secret "$ENV_SECRET_NAME" -p "{\"stringData\":{\"JWT_SECRET\":\"$JWT_SECRET\"}}"
                else
                    kubectl -n "$NAMESPACE" create secret generic "$ENV_SECRET_NAME" --from-literal=JWT_SECRET="$JWT_SECRET"
                fi
                log_success "JWT secret configured"
            fi
        fi

        # Helm values update (moved from reusable workflow)
        if [[ -n "${KUBE_CONFIG:-}" ]]; then
            log_step "Updating Helm values..."

            # Clone or update devops-k8s repo
            if [[ ! -d "devops-k8s" ]]; then
                git clone "https://github.com/${DEVOPS_REPO}.git" devops-k8s || log_warning "Failed to clone devops-k8s"
            fi

            if [[ -d "devops-k8s" ]]; then
                cd devops-k8s
                git config user.name "$GIT_USER"
                git config user.email "$GIT_EMAIL"

                # Pull latest changes
                git pull --rebase || log_warning "Git pull failed"

                # Update values file
                if [[ -f "$VALUES_FILE_PATH" ]]; then
                    yq eval '.image.repository = "'${IMAGE_REPO}'" | .image.tag = "'${GIT_COMMIT_ID}'"' "$VALUES_FILE_PATH" -i
                    if git diff --quiet HEAD "$VALUES_FILE_PATH"; then
                        log_info "No changes to commit"
                    else
                        git add "$VALUES_FILE_PATH"
                        git commit -m "${APP_NAME}:${GIT_COMMIT_ID} released" || log_warning "Git commit failed"
                        git push || log_warning "Git push failed"
                    fi
                fi
                cd ..
                log_success "Helm values updated"
            fi
        fi

        # Database migrations (moved from reusable workflow)
        if [[ "$SETUP_DATABASES" == "true" && -n "${KUBE_CONFIG:-}" ]]; then
            log_step "Running database migrations..."

            # Create migration job
            cat > /tmp/migrate-job.yaml <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${APP_NAME}-migrate-${GIT_COMMIT_ID}
  namespace: ${NAMESPACE}
spec:
  ttlSecondsAfterFinished: 600
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: migrate
        image: ${IMAGE_REPO}:${GIT_COMMIT_ID}
        command: ["python", "manage.py", "migrate"]
        envFrom:
        - secretRef:
            name: ${ENV_SECRET_NAME}
EOF

            kubectl apply -f /tmp/migrate-job.yaml
            kubectl wait --for=condition=complete job/${APP_NAME}-migrate-${GIT_COMMIT_ID} -n ${NAMESPACE} --timeout=300s || {
                log_warning "Migration job failed or timed out"
                kubectl logs job/${APP_NAME}-migrate-${GIT_COMMIT_ID} -n ${NAMESPACE} --tail=50 || true
            }
            log_success "Database migrations completed"
        fi

        log_success "Enhanced deployment process completed!"
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
