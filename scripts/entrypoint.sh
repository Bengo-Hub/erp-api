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

until /usr/local/bin/erp-migrate > /dev/null 2>&1 || [ $RETRY_COUNT -eq $MAX_RETRIES ]; do
  RETRY_COUNT=$((RETRY_COUNT+1))
  echo "Database not ready yet... (attempt $RETRY_COUNT/$MAX_RETRIES)"
  sleep 5
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "Database connection timeout after $MAX_RETRIES attempts"
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
