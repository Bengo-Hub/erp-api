#!/usr/bin/env bash
# =============================================================================
# ERP API (Go) Build and Deploy Script
# =============================================================================
# Purpose: Builds the Go Docker image, pushes to registry, runs idempotent
#          migrations/seed against the existing prod DB, and updates Helm values.
# Mirrors inventory-service/inventory-api/build.sh (Go service patterns).
#
# IMPORTANT prod facts:
#   - DB `bengo_erp` ALREADY EXISTS — this script does NOT create it.
#   - The Go ERP uses the `erp` Postgres schema (search_path=erp via DB_SCHEMA).
#   - Ent (Atlas) migrations + RBAC seed are ALREADY applied to prod; both
#     cmd/migrate and cmd/seed are idempotent, so re-running is a safe no-op.
# =============================================================================

set -euo pipefail
set +H

BLUE='\033[0;34m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

info() { echo -e "${BLUE}[INFO]${NC} $1"; }
success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
error() { echo -e "${RED}[ERROR]${NC} $1"; }

APP_NAME=${APP_NAME:-"erp-api"}
NAMESPACE=${NAMESPACE:-"erp"}
ENV_SECRET_NAME=${ENV_SECRET_NAME:-"erp-api-env"}
DEPLOY=${DEPLOY:-true}

# DB schema for the Go ERP service (search_path pinned by the app + migrate/seed).
DB_SCHEMA=${DB_SCHEMA:-"erp"}
# Run idempotent migrations + seed against the EXISTING DB. Atlas revisions make
# this a no-op when already applied. Set RUN_MIGRATIONS=false to skip entirely.
RUN_MIGRATIONS=${RUN_MIGRATIONS:-true}
RUN_SEED=${RUN_SEED:-true}

REGISTRY_SERVER=${REGISTRY_SERVER:-docker.io}
REGISTRY_NAMESPACE=${REGISTRY_NAMESPACE:-codevertex}
IMAGE_REPO="${REGISTRY_SERVER}/${REGISTRY_NAMESPACE}/${APP_NAME}"

DEVOPS_REPO=${DEVOPS_REPO:-"Bengo-Hub/devops-k8s"}
DEVOPS_DIR=${DEVOPS_DIR:-"$HOME/devops-k8s"}
VALUES_FILE_PATH=${VALUES_FILE_PATH:-"apps/${APP_NAME}/values.yaml"}

GIT_EMAIL=${GIT_EMAIL:-"dev@bengobox.com"}
GIT_USER=${GIT_USER:-"ERP Bot"}
TRIVY_ECODE=${TRIVY_ECODE:-0}

if [[ -z ${GITHUB_SHA:-} ]]; then
  GIT_COMMIT_ID=$(git rev-parse --short=8 HEAD || echo "localbuild")
else
  GIT_COMMIT_ID=${GITHUB_SHA::8}
fi

info "Service : ${APP_NAME}"
info "Namespace: ${NAMESPACE}"
info "Image   : ${IMAGE_REPO}:${GIT_COMMIT_ID}"
info "DB schema: ${DB_SCHEMA} (migrations idempotent; DB bengo_erp pre-exists)"

for tool in git docker trivy; do
  command -v "$tool" >/dev/null || { error "$tool is required"; exit 1; }
done
if [[ ${DEPLOY} == "true" ]]; then
  for tool in kubectl helm yq jq; do
    command -v "$tool" >/dev/null || { error "$tool is required"; exit 1; }
  done
fi
success "Prerequisite checks passed"

# =============================================================================
# Auto-sync secrets from devops-k8s
# =============================================================================
if [[ ${DEPLOY} == "true" ]]; then
  info "Checking and syncing required secrets from devops-k8s..."
  SYNC_SCRIPT=$(mktemp)
  if curl -fsSL "https://raw.githubusercontent.com/${DEVOPS_REPO}/main/scripts/tools/check-and-sync-secrets.sh" -o "$SYNC_SCRIPT" 2>/dev/null; then
    source "$SYNC_SCRIPT"
    check_and_sync_secrets "REGISTRY_USERNAME" "REGISTRY_PASSWORD" "GIT_TOKEN" "POSTGRES_PASSWORD" "REDIS_PASSWORD" "KUBE_CONFIG" || warn "Secret sync failed - continuing with existing secrets"
    rm -f "$SYNC_SCRIPT"
  else
    warn "Unable to download secret sync script - continuing with existing secrets"
  fi
fi

info "Running Trivy filesystem scan"
trivy fs . --exit-code "$TRIVY_ECODE" --format table || true

info "Building Docker image"
# Repo root is erp-api; Dockerfile builds ./cmd/server (Go binary).
DOCKER_BUILDKIT=1 docker build -t "${IMAGE_REPO}:${GIT_COMMIT_ID}" .
success "Docker build complete"

if [[ ${DEPLOY} != "true" ]]; then
  warn "DEPLOY=false -> skipping push/deploy"
  exit 0
fi

if [[ -n ${REGISTRY_USERNAME:-} && -n ${REGISTRY_PASSWORD:-} ]]; then
  echo "$REGISTRY_PASSWORD" | docker login "$REGISTRY_SERVER" -u "$REGISTRY_USERNAME" --password-stdin
fi

docker push "${IMAGE_REPO}:${GIT_COMMIT_ID}"
success "Image pushed"

if [[ -n ${KUBE_CONFIG:-} ]]; then
  mkdir -p ~/.kube
  if echo "$KUBE_CONFIG" | base64 -d > ~/.kube/config 2>/dev/null; then
    info "KUBE_CONFIG decoded from base64"
  else
    echo "$KUBE_CONFIG" > ~/.kube/config
    info "KUBE_CONFIG used as raw content (not base64)"
  fi
  chmod 600 ~/.kube/config
  export KUBECONFIG=~/.kube/config
fi

kubectl get ns "$NAMESPACE" >/dev/null 2>&1 || kubectl create ns "$NAMESPACE"

# =============================================================================
# Idempotent migrations + seed (DB bengo_erp / schema erp already provisioned)
# =============================================================================
# We run cmd/migrate and cmd/seed FROM the freshly built image as one-off Jobs in
# the cluster, so they execute against prod Postgres with the in-cluster network
# and the erp-api-env secret (POSTGRES_URL/POSTGRES_MIGRATE_URL). Both are
# idempotent: ent/Atlas applies only un-applied revisions (none here), and the
# RBAC seed upserts. We NEVER create or drop the database.
run_oneoff() {
  local job_suffix="$1"; shift
  local cmd_path="$1"; shift
  local job_name="${APP_NAME}-${job_suffix}-${GIT_COMMIT_ID}"
  info "Running one-off ${job_suffix} job (${cmd_path}) against schema '${DB_SCHEMA}'..."
  kubectl -n "$NAMESPACE" delete job "$job_name" --ignore-not-found >/dev/null 2>&1 || true
  cat <<EOF | kubectl -n "$NAMESPACE" apply -f -
apiVersion: batch/v1
kind: Job
metadata:
  name: ${job_name}
spec:
  backoffLimit: 1
  ttlSecondsAfterFinished: 300
  template:
    spec:
      restartPolicy: Never
      imagePullSecrets:
        - name: registry-credentials
      containers:
        - name: ${job_suffix}
          image: ${IMAGE_REPO}:${GIT_COMMIT_ID}
          command: ["${cmd_path}"]
          envFrom:
            - secretRef:
                name: ${ENV_SECRET_NAME}
          env:
            - name: DB_SCHEMA
              value: "${DB_SCHEMA}"
EOF
  kubectl -n "$NAMESPACE" wait --for=condition=complete "job/${job_name}" --timeout=300s \
    || { warn "${job_suffix} job did not complete cleanly — printing logs"; kubectl -n "$NAMESPACE" logs "job/${job_name}" --tail=50 || true; }
}

# NOTE: the Dockerfile only builds ./cmd/server. The migrate/seed entrypoints are
# invoked here only if the image ships those binaries. By default the Go server
# applies no schema changes in prod, and migrations/seed were already applied, so
# these are gated and safe to leave on (idempotent) or disable via the flags above.
if [[ -n ${KUBE_CONFIG:-} ]]; then
  if [[ "$RUN_MIGRATIONS" == "true" ]] && kubectl -n "$NAMESPACE" get secret "$ENV_SECRET_NAME" >/dev/null 2>&1; then
    run_oneoff migrate /usr/local/bin/erp-migrate || warn "migrate job skipped/failed (idempotent, non-fatal)"
  else
    info "Skipping migrations (RUN_MIGRATIONS=${RUN_MIGRATIONS} or secret ${ENV_SECRET_NAME} absent)"
  fi
  if [[ "$RUN_SEED" == "true" ]] && kubectl -n "$NAMESPACE" get secret "$ENV_SECRET_NAME" >/dev/null 2>&1; then
    run_oneoff seed /usr/local/bin/erp-seed || warn "seed job skipped/failed (idempotent, non-fatal)"
    # Global statutory payroll rates + KRA reliefs under the system tenant (idempotent).
    run_oneoff seed-payroll /usr/local/bin/erp-seed-payroll || warn "seed-payroll job skipped/failed (idempotent, non-fatal)"
    # Per-tenant HR/Ops reference defaults: job groups, leave categories, appraisal template,
    # document sequences, reliefs (idempotent; skips existing rows for every tenant shadow).
    run_oneoff seed-defaults /usr/local/bin/erp-seed-defaults || warn "seed-defaults job skipped/failed (idempotent, non-fatal)"
  else
    info "Skipping seed (RUN_SEED=${RUN_SEED} or secret ${ENV_SECRET_NAME} absent)"
  fi
fi

# Clone devops-k8s if needed for helm update
if [[ ! -d "$DEVOPS_DIR" ]]; then
  TOKEN="${GH_PAT:-${GIT_SECRET:-${GITHUB_TOKEN:-}}}"
  CLONE_URL="https://github.com/${DEVOPS_REPO}.git"
  [[ -n $TOKEN ]] && CLONE_URL="https://x-access-token:${TOKEN}@github.com/${DEVOPS_REPO}.git"
  git clone "$CLONE_URL" "$DEVOPS_DIR" || { warn "Unable to clone devops repo for helm values update"; DEVOPS_DIR=""; }
fi

# Update Helm values (image.tag) using centralized script -> ArgoCD syncs.
source "${HOME}/devops-k8s/scripts/helm/update-values.sh" 2>/dev/null || {
  [[ -n "${DEVOPS_DIR:-}" && -d "$DEVOPS_DIR" ]] && source "${DEVOPS_DIR}/scripts/helm/update-values.sh" 2>/dev/null
}
if declare -f update_helm_values >/dev/null 2>&1; then
  export GIT_EMAIL="$GIT_EMAIL"
  export GIT_USER="$GIT_USER"
  update_helm_values "$APP_NAME" "$GIT_COMMIT_ID" "$IMAGE_REPO"
else
  warn "update_helm_values function not available - helm values not updated"
fi

info "Deployment summary"
echo "  Image      : ${IMAGE_REPO}:${GIT_COMMIT_ID}"
echo "  Namespace  : ${NAMESPACE}"
echo "  DB schema  : ${DB_SCHEMA} (DB bengo_erp pre-exists; migrations idempotent)"
