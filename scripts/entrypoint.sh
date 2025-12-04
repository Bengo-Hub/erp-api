#!/bin/bash
# Entrypoint script for ERP-API service
# Runs migrations automatically before starting the server

set -e  # Exit on any error

echo "=========================================="
echo "🚀 ERP-API Service Startup"
echo "=========================================="

# Initialize media directory
echo "📁 Initializing media directory..."
/usr/local/bin/init-media.sh || echo "⚠️ Media initialization failed (non-critical)"

# Wait for database to be ready (with timeout)
echo "🔌 Waiting for database connection..."
MAX_RETRIES=3
RETRY_COUNT=0

until python manage.py check --database default > /dev/null 2>&1 || [ $RETRY_COUNT -eq $MAX_RETRIES ]; do
  RETRY_COUNT=$((RETRY_COUNT+1))
  echo "⏳ Database not ready yet... (attempt $RETRY_COUNT/$MAX_RETRIES)"
  sleep 3
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "❌ Database connection timeout after $MAX_RETRIES attempts"
  echo "📋 Last connection attempt details:"
  python manage.py check --database default 2>&1 || true
  echo ""
  echo "⚠️ Proceeding to start server anyway (will fail if DB is critical)"
else
  echo "✅ Database connected (attempt $RETRY_COUNT)"
  
  # Run database migrations (idempotent - safe to run multiple times)
  echo ""
  echo "🔄 Running database migrations..."
  if python manage.py migrate --fake-initial --noinput 2>&1; then
      echo "✅ Migrations completed successfully"
  else
      echo "⚠️ --fake-initial failed, trying regular migrate..."
      if python manage.py migrate --noinput 2>&1; then
          echo "✅ Regular migrations completed"
      else
          echo "❌ Migration failed! Service may not function correctly."
      fi
  fi
  
  # Show migration status for debugging
  echo ""
  echo "📋 Migration status (first 15 apps):"
  python manage.py showmigrations --list 2>&1 | head -40 || echo "Status check unavailable"
  
  # Seed initial required data (idempotent)
  echo ""
  echo "🌱 Seeding initial required data..."
  if python manage.py seed_initial 2>&1 | head -50; then
      echo "✅ Initial data seeded successfully"
  else
      echo "⚠️ Initial data seeding failed (non-critical)"
  fi
fi

# Collect static files (for production)
echo ""
echo "📦 Collecting static files..."
python manage.py collectstatic --noinput --clear 2>&1 | tail -5 || echo "⚠️ Static files collection failed (non-critical)"

echo ""
echo "=========================================="
echo "✅ Starting ERP-API server on port ${PORT:-4000}"
echo "=========================================="
echo ""

# Start the ASGI server (Daphne)
exec daphne -b 0.0.0.0 -p ${PORT:-4000} ProcureProKEAPI.asgi:application

