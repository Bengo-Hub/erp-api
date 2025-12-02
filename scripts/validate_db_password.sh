#!/usr/bin/env bash
# PostgreSQL password validation script
# Validates DB credentials against live cluster and returns effective password

set -euo pipefail
set +H

log_info() { echo -e "\033[0;34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[0;32m[SUCCESS]\033[0m $1"; }
log_warning() { echo -e "\033[1;33m[WARNING]\033[0m $1"; }
log_error() { echo -e "\033[0;31m[ERROR]\033[0m $1"; }
log_step() { echo -e "\033[0;35m[STEP]\033[0m $1"; }
log_debug() { echo -e "\033[0;36m[DEBUG]\033[0m $1"; }

NAMESPACE=${NAMESPACE:-erp}
APP_DB_USER=${APP_DB_USER:-erp_user}
APP_DB_NAME=${PG_DATABASE:-${DB_NAME:-bengo_erp}}
DEBUG_DB_VALIDATION=${DEBUG_DB_VALIDATION:-true}  # Force enable for debugging

log_step "Re-validating PostgreSQL password against live database..."
log_info "=== PASSWORD VALIDATION DEBUG MODE ENABLED ==="
log_info "NAMESPACE: ${NAMESPACE}"
log_info "APP_DB_USER: ${APP_DB_USER}"
log_info "APP_DB_NAME: ${APP_DB_NAME}"

# Get password from secret
log_info "Attempting to fetch PostgreSQL password from secret..."
APP_DB_PASS=$(kubectl -n "$NAMESPACE" get secret postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d || true)
if [[ -n "$APP_DB_PASS" ]]; then
    log_info "✓ Got password from postgresql secret (length: ${#APP_DB_PASS})"
    log_info "✓ Password from postgresql secret: '${APP_DB_PASS}'"
else
    log_warning "✗ PostgreSQL secret password not found"
fi

if [[ -z "$APP_DB_PASS" && -n "${POSTGRES_PASSWORD:-}" ]]; then
    log_info "Using POSTGRES_PASSWORD from env (length: ${#POSTGRES_PASSWORD})"
    log_info "✓ Password from POSTGRES_PASSWORD env: '${POSTGRES_PASSWORD}'"
    APP_DB_PASS="$POSTGRES_PASSWORD"
fi

# Optional debug helpers
debug_hash() {
  local LABEL="$1"; local VAL="$2"
  if [[ "$DEBUG_DB_VALIDATION" == "true" ]]; then
    local LEN; LEN=$(printf %s "$VAL" | wc -c | tr -d ' ')
    local SHA; SHA=$(printf %s "$VAL" | sha256sum | awk '{print $1}')
    log_debug "${LABEL}: len=${LEN}, sha256=${SHA}"
  fi
}

debug_k8s_net() {
  if [[ "$DEBUG_DB_VALIDATION" == "true" ]]; then
    log_debug "kubectl context: $(kubectl config current-context 2>/dev/null || echo 'n/a')"
    log_debug "postgresql svc: $(kubectl -n "$NAMESPACE" get svc postgresql -o jsonpath='{.spec.clusterIP}:{.spec.ports[0].port}' 2>/dev/null || echo 'n/a')"
  fi
}

debug_hash "PG_PASS_from_secret" "$APP_DB_PASS"
debug_hash "PG_PASS_from_env" "${POSTGRES_PASSWORD:-}"
debug_k8s_net

try_psql_user() {
  local PASS="$1"; local USER="$2"; local DBNAME="$3"
  local JOB_NAME="pguser-check-${RANDOM}"
  
  log_debug "    try_psql_user called with:"
  log_debug "      USER: '${USER}'"
  log_debug "      DBNAME: '${DBNAME}'"
  log_debug "      PASS: '${PASS}' (length: ${#PASS})"
  log_debug "      JOB_NAME: '${JOB_NAME}'"
  
  if [[ -z "$PASS" || -z "$USER" || -z "$DBNAME" ]]; then
    log_debug "    → Validation check failed (missing params)"
    return 1
  fi
  
  log_debug "    → Creating test job in namespace '${NAMESPACE}'..."
  cat > /tmp/${JOB_NAME}.yaml <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${JOB_NAME}
  namespace: ${NAMESPACE}
spec:
  ttlSecondsAfterFinished: 120
  backoffLimit: 0
  template:
    spec:
      restartPolicy: Never
      containers:
      - name: psql
        image: postgres:18
        env:
        - name: PGPASSWORD
          value: "${PASS}"
        command: ["psql"]
        args: ["-h","postgresql.${NAMESPACE}.svc.cluster.local","-U","${USER}","-d","${DBNAME}","-c","SELECT current_user, current_database();"]
EOF
  
  log_debug "    → Applying job manifest..."
  set +e
  local APPLY_OUT=$(kubectl apply -f /tmp/${JOB_NAME}.yaml 2>&1)
  local APPLY_RC=$?
  log_debug "    → kubectl apply RC: ${APPLY_RC}"
  if [[ ${APPLY_RC} -ne 0 ]]; then
    log_debug "    → kubectl apply output: ${APPLY_OUT}"
  fi
  
  log_debug "    → Waiting for job completion (45s timeout)..."
  kubectl -n "$NAMESPACE" wait --for=condition=complete job/${JOB_NAME} --timeout=45s >/dev/null 2>&1
  local RC=$?
  log_debug "    → Job completion RC: ${RC}"
  
  if [[ "$DEBUG_DB_VALIDATION" == "true" ]]; then
    log_debug "    → Fetching job logs:"
    log_debug "----------------------------------------"
    kubectl -n "$NAMESPACE" logs job/${JOB_NAME} 2>/dev/null || log_debug "(no logs available)"
    log_debug "----------------------------------------"
  fi
  
  log_debug "    → Cleaning up job..."
  kubectl -n "$NAMESPACE" delete job ${JOB_NAME} --ignore-not-found >/dev/null 2>&1 || true
  rm -f /tmp/${JOB_NAME}.yaml 2>/dev/null || true
  
  set -e
  log_debug "    → Returning RC: ${RC}"
  return $RC
}

# Pull live password once for candidate list (only if kubeconfig available)
LIVE_PG_PASS=""
log_info "Checking kubectl availability..."
if kubectl version --short >/dev/null 2>&1; then
  log_info "✓ kubectl is available"
  LIVE_PG_PASS=$(kubectl -n "$NAMESPACE" get secret postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d || true)
  if [[ -n "$LIVE_PG_PASS" ]]; then
    log_info "✓ Got password from live postgresql secret (length: ${#LIVE_PG_PASS})"
    log_info "✓ Live password: '${LIVE_PG_PASS}'"
  else
    log_warning "✗ Could not fetch live postgresql secret"
  fi
  debug_hash "PG_PASS_from_live_secret" "$LIVE_PG_PASS"
else
  log_warning "✗ kubectl not available or not configured; skipping live secret fetch"
fi

# If application secret already exists and has DB_PASSWORD, prefer it
log_info "Checking application secret ${ENV_SECRET_NAME:-erp-api-env}..."
SECRET_DB_PASS=$(kubectl -n "$NAMESPACE" get secret ${ENV_SECRET_NAME:-erp-api-env} -o jsonpath='{.data.DB_PASSWORD}' 2>/dev/null | base64 -d || true)
if [[ -n "$SECRET_DB_PASS" ]]; then
  log_info "✓ Got password from app secret DB_PASSWORD (length: ${#SECRET_DB_PASS})"
  log_info "✓ App secret DB_PASSWORD: '${SECRET_DB_PASS}'"
else
  log_info "✗ No DB_PASSWORD in app secret"
fi

SECRET_URL_PASS=$(kubectl -n "$NAMESPACE" get secret ${ENV_SECRET_NAME:-erp-api-env} -o jsonpath='{.data.DATABASE_URL}' 2>/dev/null | base64 -d | sed -n 's#.*postgresql://[^:]*:\([^@]*\)@.*#\1#p' || true)
if [[ -n "$SECRET_URL_PASS" ]]; then
  log_info "✓ Extracted password from DATABASE_URL (length: ${#SECRET_URL_PASS})"
  log_info "✓ DATABASE_URL password: '${SECRET_URL_PASS}'"
else
  log_info "✗ Could not extract password from DATABASE_URL"
fi

debug_hash "PG_PASS_from_app_secret" "$SECRET_DB_PASS"
debug_hash "PG_PASS_from_DATABASE_URL" "$SECRET_URL_PASS"

log_info "=== Building candidate password list ==="
CANDIDATE_PASSES=("$APP_DB_PASS" "${POSTGRES_PASSWORD:-}" "$LIVE_PG_PASS" "$SECRET_DB_PASS" "$SECRET_URL_PASS")
log_info "Total candidates: ${#CANDIDATE_PASSES[@]}"
for i in "${!CANDIDATE_PASSES[@]}"; do
  if [[ -n "${CANDIDATE_PASSES[$i]}" ]]; then
    log_info "  Candidate $((i+1)): '${CANDIDATE_PASSES[$i]}' (length: ${#CANDIDATE_PASSES[$i]})"
  else
    log_info "  Candidate $((i+1)): (empty)"
  fi
done
EFFECTIVE_PG_PASS=""
VALIDATED_USER=""

log_info "=== Testing candidate passwords against database ==="
CANDIDATE_NUM=0
for CANDIDATE in "${CANDIDATE_PASSES[@]}"; do
  CANDIDATE_NUM=$((CANDIDATE_NUM + 1))
  if [[ -z "$CANDIDATE" ]]; then
    log_info "Skipping candidate ${CANDIDATE_NUM} (empty)"
    continue
  fi
  
  log_info "Testing candidate ${CANDIDATE_NUM}: '${CANDIDATE}'"
  
  # Try with intended app user first
  log_info "  → Trying with user '${APP_DB_USER}' on database '${APP_DB_NAME}'..."
  if try_psql_user "$CANDIDATE" "$APP_DB_USER" "$APP_DB_NAME"; then
    log_success "  ✓ SUCCESS! Password works with user '${APP_DB_USER}'"
    EFFECTIVE_PG_PASS="$CANDIDATE"
    VALIDATED_USER="$APP_DB_USER"
    break
  else
    log_warning "  ✗ Failed with user '${APP_DB_USER}'"
  fi
  
  # Fallback: try with postgres user to same DB
  log_info "  → Trying with user 'postgres' on database '${APP_DB_NAME}'..."
  if try_psql_user "$CANDIDATE" "postgres" "$APP_DB_NAME"; then
    log_success "  ✓ SUCCESS! Password works with user 'postgres'"
    EFFECTIVE_PG_PASS="$CANDIDATE"
    VALIDATED_USER="postgres"
    break
  else
    log_warning "  ✗ Failed with user 'postgres'"
  fi
  
  log_warning "Candidate ${CANDIDATE_NUM} failed all tests"
done

if [[ -z "$EFFECTIVE_PG_PASS" ]]; then
  log_error "═══════════════════════════════════════════════════════════════"
  log_error "CRITICAL: Could not validate any password!"
  log_error "═══════════════════════════════════════════════════════════════"
  log_error "Tested ${CANDIDATE_NUM} candidate(s)"
  log_error "Target users: '${APP_DB_USER}' and 'postgres'"
  log_error "Target database: '${APP_DB_NAME}'"
  log_error "Target namespace: '${NAMESPACE}'"
  log_error ""
  log_error "All candidates failed. Check the logs above for details."
  log_error "═══════════════════════════════════════════════════════════════"
  exit 1
else
  log_success "═══════════════════════════════════════════════════════════════"
  log_success "Database credentials validated successfully!"
  log_success "User: '${VALIDATED_USER}'"
  log_success "Database: '${APP_DB_NAME}'"
  log_success "Password: '${EFFECTIVE_PG_PASS}'"
  log_success "═══════════════════════════════════════════════════════════════"
fi

# Export validated credentials for parent script
echo "EFFECTIVE_PG_PASS=${EFFECTIVE_PG_PASS}"
echo "VALIDATED_DB_USER=${VALIDATED_USER}"
echo "VALIDATED_DB_NAME=${APP_DB_NAME}"

