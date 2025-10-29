#!/usr/bin/env bash
# Database seeding script
# Seeds initial data as a Kubernetes Job

set -euo pipefail

log_info() { echo -e "\033[0;34m[INFO]\033[0m $1"; }
log_success() { echo -e "\033[0;32m[SUCCESS]\033[0m $1"; }
log_error() { echo -e "\033[0;31m[ERROR]\033[0m $1"; }
log_step() { echo -e "\033[0;35m[STEP]\033[0m $1"; }

# Required variables
APP_NAME=${APP_NAME:-erp-api}
IMAGE_REPO=${IMAGE_REPO:-}
GIT_COMMIT_ID=${GIT_COMMIT_ID:-}
NAMESPACE=${NAMESPACE:-erp}
ENV_SECRET_NAME=${ENV_SECRET_NAME:-erp-api-env}

if [[ -z "$IMAGE_REPO" || -z "$GIT_COMMIT_ID" ]]; then
    log_error "IMAGE_REPO and GIT_COMMIT_ID are required"
    exit 1
fi

log_step "Seeding initial data (minimal mode for safety)"

# Create seed job with imagePullSecrets if needed
PULL_SECRETS_YAML=""
if kubectl -n "$NAMESPACE" get secret registry-credentials >/dev/null 2>&1; then
    PULL_SECRETS_YAML="      imagePullSecrets:
      - name: registry-credentials"
fi

cat > /tmp/seed-job.yaml <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${APP_NAME}-seed-${GIT_COMMIT_ID}
  namespace: ${NAMESPACE}
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 1
  template:
    spec:
      restartPolicy: Never
${PULL_SECRETS_YAML}
      containers:
      - name: seed
        image: ${IMAGE_REPO}:${GIT_COMMIT_ID}
        command:
        - bash
        - -c
        - |
          set -e
          echo "==================================="
          echo "Django Seeding - Smart Mode"
          echo "==================================="
          
          # Install PostgreSQL client for table checking
          apt-get update -qq && apt-get install -y -qq postgresql-client >/dev/null 2>&1 || true
          
          # Check if database has existing data
          echo "Checking if database has existing data..."
          TABLE_COUNT=\$(PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
            -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | xargs || echo "0")
          
          echo "Database has \$TABLE_COUNT tables"
          
          # Check if seed data already exists (check auth_user table)
          USER_COUNT=0
          if PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
            -c "SELECT COUNT(*) FROM auth_user;" 2>/dev/null | grep -q .; then
            USER_COUNT=\$(PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
              -c "SELECT COUNT(*) FROM auth_user;" 2>/dev/null | xargs || echo "0")
          fi
          
          echo "Database has \$USER_COUNT users"
          
          # Decision: Skip clearing if database has data (avoids deleting from missing tables)
          if [[ "\$USER_COUNT" -gt "0" ]]; then
            echo "✓ Existing data detected - seeding with --no-clear to preserve data"
            echo "Running: python manage.py seed_all --minimal --no-clear"
            python manage.py seed_all --minimal --no-clear || {
              echo "⚠️  Seeding with --no-clear failed (may have conflicts)"
              echo "Attempting to seed critical data only..."
              python manage.py seed_core_data || true
              python manage.py seed_business_data || true
              echo "✓ Critical data seeded (some failures ignored)"
            }
          else
            echo "✓ Fresh database - seeding with data clearing enabled"
            echo "Running: python manage.py seed_all --minimal"
            python manage.py seed_all --minimal
          fi
          
          echo "✅ Seeding completed"
        envFrom:
        - secretRef:
            name: ${ENV_SECRET_NAME}
EOF

# Source stream_job helper if available, otherwise define inline
if [[ $(type -t stream_job) != "function" ]]; then
    stream_job() {
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
fi

set +e
kubectl apply -f /tmp/seed-job.yaml
# Increased timeout to 600s (10 minutes) to handle large seeding operations
stream_job "${NAMESPACE}" "${APP_NAME}-seed-${GIT_COMMIT_ID}" "600s"
SEED_STATUS=$?
set -e

if [[ $SEED_STATUS -ne 0 ]]; then
  log_error "Seed job failed or timed out"
  exit 1
fi

log_success "Initial data seeding completed"

