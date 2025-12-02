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
        # Increase file descriptor limits to prevent "too many open files" errors
        securityContext:
          capabilities:
            add:
            - SYS_RESOURCE
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "2Gi"
            cpu: "1000m"
        command: 
        - bash
        - -c
        - |
          set -e
          
          # Increase file descriptor limits immediately
          ulimit -n 65535 || echo "⚠️  Could not increase file descriptor limit"
          
          echo "==================================="
          echo "Django Migrations - Smart Mode"
          echo "==================================="
          echo "File descriptor limit: \$(ulimit -n)"
          
          # Install PostgreSQL client for table checking (minimize file operations)
          export DEBIAN_FRONTEND=noninteractive
          apt-get update -qq -o Dir::Etc::sourcelist=/etc/apt/sources.list.d/debian.sources \
            -o Dir::Etc::sourceparts="-" -o APT::Get::List-Cleanup="0" && \
          apt-get install -y -qq --no-install-recommends postgresql-client >/dev/null 2>&1 || true
          apt-get clean && rm -rf /var/lib/apt/lists/* || true
          
          # Wait for database to be fully ready with retry logic
          echo "Waiting for database connection..."
          MAX_RETRIES=30
          RETRY_COUNT=0
          DB_READY=false
          
          while [ \$RETRY_COUNT -lt \$MAX_RETRIES ]; do
            if PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" \
              -c "SELECT 1" >/dev/null 2>&1; then
              DB_READY=true
              echo "✓ Database connection established"
              break
            fi
            RETRY_COUNT=\$((RETRY_COUNT + 1))
            echo "Waiting for database... (attempt \$RETRY_COUNT/\$MAX_RETRIES)"
            sleep 2
          done
          
          if [ "\$DB_READY" = "false" ]; then
            echo "✗ Failed to connect to database after \$MAX_RETRIES attempts"
            exit 1
          fi
          
          # Give database a moment to stabilize
          sleep 3
          
          # Check database state by counting tables
          echo "Checking database state..."
          TABLE_COUNT=\$(PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
            -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public';" 2>/dev/null | xargs || echo "0")
          
          echo "Database has \$TABLE_COUNT tables"
          
          # Check if critical core tables exist (indicates properly migrated database)
          # Use a single query to reduce file descriptors and improve performance
          CORE_TABLES_EXIST=\$(PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
            -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('auth_user', 'django_migrations', 'core_businessdetail', 'core_department', 'core_region');" \
            2>/dev/null | xargs || echo "0")
          
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
          
          # Verify critical tables exist after migrations (single query for efficiency)
          echo "Verifying critical tables..."
          EXPECTED_TABLES="('auth_user', 'django_migrations', 'core_businessdetail', 'attendance_timesheet')"
          FOUND_TABLES=\$(PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
            -c "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN \$EXPECTED_TABLES;" \
            2>/dev/null | xargs || echo "0")
          
          if [[ "\$FOUND_TABLES" -lt "4" ]]; then
            echo "⚠️  WARNING: Some expected tables are missing after migrations:"
            echo "   Expected 4 critical tables, found \$FOUND_TABLES"
            
            # Get list of missing tables with single query
            MISSING=\$(PGPASSWORD="\$DB_PASSWORD" psql -h "\$DB_HOST" -p "\$DB_PORT" -U "\$DB_USER" -d "\$DB_NAME" -t \
              -c "SELECT unnest(ARRAY['auth_user', 'django_migrations', 'core_businessdetail', 'attendance_timesheet']) 
                  EXCEPT 
                  SELECT table_name FROM information_schema.tables WHERE table_schema='public' AND table_name IN \$EXPECTED_TABLES;" \
              2>/dev/null | sed 's/^[ \t]*//')
            
            if [[ -n "\$MISSING" ]]; then
              echo "   Missing tables:"
              echo "\$MISSING" | while read -r table; do
                [[ -n "\$table" ]] && echo "     - \$table"
              done
            fi
            
            echo "This may cause seeding failures. Consider investigating migration issues."
          else
            echo "✓ All critical tables verified (\$FOUND_TABLES/4)"
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
# Increased timeout to 600s (10 minutes) to handle large number of migrations
stream_job "${NAMESPACE}" "${APP_NAME}-migrate-${GIT_COMMIT_ID}" "600s"
JOB_STATUS=$?
set -e

if [[ $JOB_STATUS -ne 0 ]]; then
    log_error "Migration job failed or timed out"
    exit 1
fi

log_success "Database migrations completed"

