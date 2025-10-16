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
APP_DB_NAME=${PG_DATABASE:-bengo_erp}
DEBUG_DB_VALIDATION=${DEBUG_DB_VALIDATION:-false}

log_step "Re-validating PostgreSQL password against live database..."

# Get password from secret
APP_DB_PASS=$(kubectl -n "$NAMESPACE" get secret postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d || true)
if [[ -z "$APP_DB_PASS" && -n "${POSTGRES_PASSWORD:-}" ]]; then
    log_info "PostgreSQL secret password not found; using POSTGRES_PASSWORD from env"
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
  if [[ -z "$PASS" || -z "$USER" || -z "$DBNAME" ]]; then return 1; fi
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
        image: registry-1.docker.io/bitnami/postgresql:15
        env:
        - name: PGPASSWORD
          value: "${PASS}"
        command: ["psql"]
        args: ["-h","postgresql.${NAMESPACE}.svc.cluster.local","-U","${USER}","-d","${DBNAME}","-c","SELECT current_user, current_database();"]
EOF
  set +e
  kubectl apply -f /tmp/${JOB_NAME}.yaml >/dev/null 2>&1
  kubectl -n "$NAMESPACE" wait --for=condition=complete job/${JOB_NAME} --timeout=45s >/dev/null 2>&1
  local RC=$?
  if [[ "$DEBUG_DB_VALIDATION" == "true" ]]; then
    log_debug "psql user job logs (user=${USER}, db=${DBNAME}, RC=${RC}):"
    kubectl -n "$NAMESPACE" logs job/${JOB_NAME} 2>/dev/null || true
  fi
  kubectl -n "$NAMESPACE" delete job ${JOB_NAME} --ignore-not-found >/dev/null 2>&1 || true
  set -e
  return $RC
}

# Pull live password once for candidate list (only if kubeconfig available)
LIVE_PG_PASS=""
if kubectl version --short >/dev/null 2>&1; then
  LIVE_PG_PASS=$(kubectl -n "$NAMESPACE" get secret postgresql -o jsonpath='{.data.postgres-password}' 2>/dev/null | base64 -d || true)
  debug_hash "PG_PASS_from_live_secret" "$LIVE_PG_PASS"
else
  log_info "kubectl not available or not configured; skipping live secret fetch"
fi

CANDIDATE_PASSES=("$APP_DB_PASS" "${POSTGRES_PASSWORD:-}" "$LIVE_PG_PASS")
EFFECTIVE_PG_PASS=""
VALIDATED_USER=""

for CANDIDATE in "${CANDIDATE_PASSES[@]}"; do
  [[ -z "$CANDIDATE" ]] && continue
  # Try with intended app user first
  if try_psql_user "$CANDIDATE" "$APP_DB_USER" "$APP_DB_NAME"; then
    EFFECTIVE_PG_PASS="$CANDIDATE"
    VALIDATED_USER="$APP_DB_USER"
    break
  fi
  # Fallback: try with postgres user to same DB
  if try_psql_user "$CANDIDATE" "postgres" "$APP_DB_NAME"; then
    EFFECTIVE_PG_PASS="$CANDIDATE"
    VALIDATED_USER="postgres"
    break
  fi
done

if [[ -z "$EFFECTIVE_PG_PASS" ]]; then
  log_error "CRITICAL: Could not validate any password for users '${APP_DB_USER}' or 'postgres'"
  log_error "Enable DEBUG_DB_VALIDATION=true for detailed diagnostics"
  exit 1
else
  log_success "Database credentials validated for user '${VALIDATED_USER}' and db '${APP_DB_NAME}'"
fi

# Export validated credentials for parent script
echo "EFFECTIVE_PG_PASS=${EFFECTIVE_PG_PASS}"
echo "VALIDATED_DB_USER=${VALIDATED_USER}"
echo "VALIDATED_DB_NAME=${APP_DB_NAME}"

