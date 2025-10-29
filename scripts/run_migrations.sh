#!/usr/bin/env bash
# Database migration script
# Runs Django migrations as a Kubernetes Job

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

log_step "Running database migrations..."

# Verify env secret exists
if ! kubectl -n "$NAMESPACE" get secret "$ENV_SECRET_NAME" >/dev/null 2>&1; then
    log_error "Environment secret ${ENV_SECRET_NAME} not found; cannot run migrations"
    exit 1
fi
log_info "Environment secret ${ENV_SECRET_NAME} verified"

# Create migration job with imagePullSecrets if needed
PULL_SECRETS_YAML=""
if kubectl -n "$NAMESPACE" get secret registry-credentials >/dev/null 2>&1; then
    PULL_SECRETS_YAML="      imagePullSecrets:
      - name: registry-credentials"
fi

cat > /tmp/migrate-job.yaml <<EOF
apiVersion: batch/v1
kind: Job
metadata:
  name: ${APP_NAME}-migrate-${GIT_COMMIT_ID}
  namespace: ${NAMESPACE}
spec:
  ttlSecondsAfterFinished: 600
  backoffLimit: 2
  template:
    spec:
      restartPolicy: Never
${PULL_SECRETS_YAML}
      containers:
      - name: migrate
        image: ${IMAGE_REPO}:${GIT_COMMIT_ID}
        command: 
        - bash
        - -c
        - |
          set -e
          echo "==================================="
          echo "Django Migrations - Smart Mode"
          echo "==================================="
          
          # Install PostgreSQL client for table checking
          apt-get update -qq && apt-get install -y -qq postgresql-client >/dev/null 2>&1 || true
          
          # Check database state by counting tables
          echo "Checking database state..."
          TABLE_COUNT=\$(PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
            -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | xargs || echo "0")
          
          echo "Database has \$TABLE_COUNT tables"
          
          # Check if critical core tables exist (indicates properly migrated database)
          CORE_TABLES_EXIST=0
          for table in auth_user django_migrations core_businessdetail core_department core_region; do
            if PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
              -c "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='\$table';" 2>/dev/null | grep -q 1; then
              ((CORE_TABLES_EXIST++))
            fi
          done
          
          echo "Core tables found: \$CORE_TABLES_EXIST/5"
          
          # Decision tree for migration strategy
          if [[ "\$TABLE_COUNT" -eq "0" ]]; then
            echo "✓ Fresh database (0 tables) - running normal migrations"
            python manage.py migrate --noinput
            
          elif [[ "\$CORE_TABLES_EXIST" -ge "4" ]]; then
            echo "✓ Well-established database (\$CORE_TABLES_EXIST/5 core tables) - using --fake-initial"
            python manage.py migrate --fake-initial --noinput || {
              echo "⚠️  --fake-initial failed, trying regular migrate..."
              python manage.py migrate --noinput
            }
            
          else
            echo "⚠️  Partial database (\$TABLE_COUNT tables but only \$CORE_TABLES_EXIST/5 core) - using regular migrations"
            echo "This may fail if schema conflicts exist, but will ensure all tables are created"
            python manage.py migrate --noinput || {
              echo "⚠️  Regular migrate failed due to conflicts - trying --fake-initial as last resort..."
              python manage.py migrate --fake-initial --noinput || {
                echo "✗ Both migration strategies failed - database may be in inconsistent state"
                exit 1
              }
            }
          fi
          
          echo "✅ Migrations completed successfully"
          
          # Verify critical tables exist after migrations
          echo "Verifying critical tables..."
          MISSING_TABLES=()
          for table in auth_user django_migrations core_businessdetail attendance_timesheet; do
            if ! PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
              -c "SELECT 1 FROM information_schema.tables WHERE table_schema='public' AND table_name='\$table';" 2>/dev/null | grep -q 1; then
              MISSING_TABLES+=("\$table")
            fi
          done
          
          if [[ \${#MISSING_TABLES[@]} -gt 0 ]]; then
            echo "⚠️  WARNING: Some expected tables are missing after migrations:"
            printf '  - %s\n' "\${MISSING_TABLES[@]}"
            echo "This may cause seeding failures. Consider investigating migration issues."
          else
            echo "✓ All critical tables verified"
          fi
        env:
        - name: DATABASE_URL
          valueFrom:
            secretKeyRef:
              name: ${ENV_SECRET_NAME}
              key: DATABASE_URL
        - name: DB_HOST
          valueFrom:
            secretKeyRef:
              name: ${ENV_SECRET_NAME}
              key: DB_HOST
        - name: DB_PORT
          valueFrom:
            secretKeyRef:
              name: ${ENV_SECRET_NAME}
              key: DB_PORT
        - name: DB_NAME
          valueFrom:
            secretKeyRef:
              name: ${ENV_SECRET_NAME}
              key: DB_NAME
        - name: DB_USER
          valueFrom:
            secretKeyRef:
              name: ${ENV_SECRET_NAME}
              key: DB_USER
        - name: DB_PASSWORD
          valueFrom:
            secretKeyRef:
              name: ${ENV_SECRET_NAME}
              key: DB_PASSWORD
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
kubectl apply -f /tmp/migrate-job.yaml
stream_job "${NAMESPACE}" "${APP_NAME}-migrate-${GIT_COMMIT_ID}" "300s"
JOB_STATUS=$?
set -e

if [[ $JOB_STATUS -ne 0 ]]; then
    log_error "Migration job failed or timed out"
    exit 1
fi

log_success "Database migrations completed"

