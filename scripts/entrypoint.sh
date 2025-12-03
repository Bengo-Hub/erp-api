#!/bin/bash
# Entrypoint script for ERP-API service
# Runs migrations automatically before starting the server

set -e  # Exit on any error

echo "=========================================="
echo "ERP-API Service Startup"
echo "=========================================="

# Initialize media directory
echo "📁 Initializing media directory..."
/usr/local/bin/init-media.sh || echo "⚠️ Media initialization failed (non-critical)"

# Wait for database to be ready (with timeout)
echo "🔌 Waiting for database connection..."
MAX_RETRIES=30
RETRY_COUNT=0

until python manage.py check --database default > /dev/null 2>&1 || [ $RETRY_COUNT -eq $MAX_RETRIES ]; do
  RETRY_COUNT=$((RETRY_COUNT+1))
  echo "⏳ Database not ready yet... (attempt $RETRY_COUNT/$MAX_RETRIES)"
  sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "❌ Database connection timeout after $MAX_RETRIES attempts"
  echo "⚠️ Proceeding anyway (migrations will fail if DB is down)"
fi

# Run database migrations (idempotent - safe to run multiple times)
echo "🔄 Running database migrations..."
python manage.py migrate --noinput

if [ $? -eq 0 ]; then
    echo "✅ Migrations completed successfully"
else
    echo "❌ Migration failed! Service may not function correctly."
    # Don't exit - let the service start so logs are accessible
fi

# Collect static files (for production)
echo "📦 Collecting static files..."
python manage.py collectstatic --noinput || echo "⚠️ Static files collection failed (non-critical)"

# Show migration status for debugging
echo "📋 Current migration status:"
python manage.py showmigrations --list | grep -E "^\[X\]|^\[ \]" | head -20 || echo "Status check unavailable"

echo "=========================================="
echo "🚀 Starting ERP-API server on port ${PORT:-4000}..."
echo "=========================================="

# Start the ASGI server (Daphne)
exec daphne -b 0.0.0.0 -p ${PORT:-4000} ProcureProKEAPI.asgi:application

