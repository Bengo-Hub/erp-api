#!/bin/sh
# Entrypoint script for ERP-API service
# Runs migrations and seed (idempotent) before starting the server, matching the
# inventory/pos/logistics/subscriptions Go-backend pattern.

set -e

echo "=========================================="
echo "ERP-API Service Startup"
echo "=========================================="

echo "Waiting for database and running migrations..."
MAX_RETRIES=60
RETRY_COUNT=0

# Captured (not swallowed) so a real migration failure is visible on every attempt -- the
# liveness probe usually kills this container long before MAX_RETRIES is ever reached.
until MIGRATE_OUTPUT=$(/usr/local/bin/erp-migrate 2>&1) || [ $RETRY_COUNT -eq $MAX_RETRIES ]; do
  RETRY_COUNT=$((RETRY_COUNT+1))
  echo "Migration attempt $RETRY_COUNT/$MAX_RETRIES failed:"
  echo "$MIGRATE_OUTPUT"
  sleep 5
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "Migration failed after $MAX_RETRIES attempts. Last error:"
  echo "$MIGRATE_OUTPUT"
  exit 1
fi

echo "Migrations applied successfully"

echo ""
echo "=========================================="
echo "Running seed (idempotent)"
echo "=========================================="
/usr/local/bin/erp-seed || echo "RBAC seed completed with warnings (non-fatal)"
/usr/local/bin/erp-seed-payroll || echo "Global payroll seed completed with warnings (non-fatal)"
/usr/local/bin/erp-seed-defaults || echo "Per-tenant defaults seed completed with warnings (non-fatal)"

echo ""
echo "=========================================="
echo "Starting ERP-API server"
echo "=========================================="
echo ""

exec /usr/local/bin/erp-api
