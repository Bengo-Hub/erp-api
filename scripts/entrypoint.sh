#!/bin/bash
# Entrypoint script for ERP-API service
# Runs migrations only if pending migrations exist (idempotent for multi-pod deployments)
# Multiple pods connect to the same database, so we must avoid redundant migrations

set -e  # Exit on any error

echo "=========================================="
echo "🚀 ERP-API Service Startup"
echo "=========================================="

# Log configuration for debugging
echo "📋 Configuration:"
echo "   Environment: ${DJANGO_ENV:-production}"
echo "   Debug mode: ${DEBUG:-False}"
echo "   Port: ${PORT:-4000}"

# Initialize media directory
echo "📁 Initializing media directory..."
/usr/local/bin/init-media.sh || echo "⚠️ Media initialization failed (non-critical)"

# Wait for database to be ready (with timeout)
echo "🔌 Waiting for database connection..."
# Increased retries for production stability (60 * 5s = 5 minutes)
MAX_RETRIES=60
RETRY_COUNT=0

until python manage.py check --database default > /dev/null 2>&1 || [ $RETRY_COUNT -eq $MAX_RETRIES ]; do
  RETRY_COUNT=$((RETRY_COUNT+1))
  echo "⏳ Database not ready yet... (attempt $RETRY_COUNT/$MAX_RETRIES)"
  sleep 5
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "❌ Database connection timeout after $MAX_RETRIES attempts"
  echo "📋 Last connection attempt details:"
  python manage.py check --database default 2>&1 || true
  echo ""
  echo "⚠️ Proceeding to start server anyway (will fail if DB is critical)"
else
  echo "✅ Database connected (attempt $RETRY_COUNT)"
  
  # Check for pending migrations (idempotent multi-pod pattern)
  echo ""
  echo "🔍 Checking for pending migrations..."
  PENDING_MIGRATIONS=$(python manage.py showmigrations --plan 2>&1 | grep -c '^\s*\[ \]' || true)
  
  if [ "$PENDING_MIGRATIONS" -gt 0 ]; then
    echo "📋 Found $PENDING_MIGRATIONS pending migrations - acquiring migration lock (timeout: 30s)..."
    
    # Fast lock using database with short timeout (30s total wait)
    LOCK_ACQUIRED=0
    LOCK_ATTEMPTS=0
    MAX_LOCK_ATTEMPTS=6  # 6 attempts × 5s = 30s max wait

    while [ $LOCK_ATTEMPTS -lt $MAX_LOCK_ATTEMPTS ] && [ $LOCK_ACQUIRED -eq 0 ]; do
      LOCK_ATTEMPTS=$((LOCK_ATTEMPTS + 1))
      
      # Try to acquire lock using Django shell
      if python manage.py shell -c "
from django.db import connection
from datetime import datetime, timedelta

with connection.cursor() as cursor:
    # Create migrations_lock table if not exists (idempotent)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS migrations_lock (
            id SERIAL PRIMARY KEY,
            lock_name VARCHAR(255) UNIQUE,
            acquired_at TIMESTAMP DEFAULT NOW()
        )
    ''')
    connection.commit()
    
    # Try to acquire lock with 60-second expiry (only 1 pod runs migrations per 60s window)
    try:
        cursor.execute('''
            DELETE FROM migrations_lock 
            WHERE lock_name = 'erp_migrations' 
            AND acquired_at < NOW() - INTERVAL '60 seconds'
        ''')
        
        cursor.execute('''
            INSERT INTO migrations_lock (lock_name, acquired_at)
            VALUES ('erp_migrations', NOW())
            ON CONFLICT (lock_name) DO NOTHING
        ''')
        connection.commit()
        
        # Check if insert succeeded (lock acquired)
        cursor.execute('SELECT COUNT(*) FROM migrations_lock WHERE lock_name = %s', ['erp_migrations'])
        count = cursor.fetchone()[0]
        if count > 0:
            print('LOCK_ACQUIRED')
    except Exception as e:
        pass
" 2>&1 | grep -q "LOCK_ACQUIRED"; then
        LOCK_ACQUIRED=1
        echo "✅ Migration lock acquired - running migrations..."
        
        # Run database migrations with timeout
        if timeout 300 python manage.py migrate --noinput 2>&1; then
            echo "✅ Migrations completed successfully"
        else
            echo "❌ Migrations failed or timed out! Proceeding anyway (Django tracks state)."
        fi
      else
        # Lock not acquired - other pod is migrating, wait
        if [ $LOCK_ATTEMPTS -lt $MAX_LOCK_ATTEMPTS ]; then
          echo "⏳ Migration lock held by another pod (attempt $LOCK_ATTEMPTS/$MAX_LOCK_ATTEMPTS, waiting 5s)..."
          sleep 5
        fi
      fi
    done
    
    if [ $LOCK_ACQUIRED -eq 0 ]; then
      echo "⚠️ Timed out waiting for migration lock after 30s"
      echo "   Proceeding to start server (other pod should have completed migrations)"
      echo "   If migrations are still pending, the health check will retry"
    fi
  else
    echo "✅ No pending migrations - all migrations already applied"
  fi
  
  # Show migration status for debugging (non-blocking)
  echo ""
  echo "📋 Migration status (first 20 apps):"
  python manage.py showmigrations --list 2>&1 | head -25 || echo "Status check unavailable"
  
  # Seed initial required data (idempotent)
  echo ""
  echo "🌱 Seeding initial required data..."
  if python manage.py seed_initial 2>&1 | head -50; then
      echo "✅ Initial data seeded successfully"
  else
      echo "⚠️ Initial data seeding failed (non-critical)"
  fi
fi

# Verify/collect static files (for production)
# Static files should already be collected during Docker build, this is a safety net
echo ""
echo "📦 Verifying static files..."
FILE_COUNT=$(find /app/staticfiles -type f 2>/dev/null | wc -l || echo 0)
if [ "$FILE_COUNT" -gt 500 ]; then
    echo "✅ Static files already collected: $FILE_COUNT files in /app/staticfiles/"
    echo "   Skipping collectstatic (files baked into Docker image)"
else
    echo "⚠️ Static files not found in image ($FILE_COUNT files), collecting now..."
    COLLECTSTATIC_LOG=$(mktemp)
    if python manage.py collectstatic --noinput --clear > "$COLLECTSTATIC_LOG" 2>&1; then
        COLLECTED=$(grep -E "^[0-9]+ static" "$COLLECTSTATIC_LOG" 2>/dev/null | tail -1 || echo "completed")
        echo "✅ Static files collected: $COLLECTED"

        FILE_COUNT=$(find /app/staticfiles -type f 2>/dev/null | wc -l || echo 0)
        if [ "$FILE_COUNT" -gt 100 ]; then
            echo "✅ Verified: $FILE_COUNT files in /app/staticfiles/"
        else
            echo "⚠️ WARNING: Only $FILE_COUNT static files collected (expected 1000+)"
            echo "   Admin panel styling may be missing in production"
        fi
        rm -f "$COLLECTSTATIC_LOG"
    else
        echo "❌ ERROR: Static files collection FAILED!"
        echo "   Admin panel styling will be broken - see errors below:"
        tail -30 "$COLLECTSTATIC_LOG"
        rm -f "$COLLECTSTATIC_LOG"
    fi
fi

# Create logo placeholder for admin panel if missing
if [ ! -f /app/staticfiles/logo/logo.png ]; then
    echo "🎨 Creating logo placeholder for admin panel..."
    mkdir -p /app/staticfiles/logo
    echo -n "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==" | base64 -d > /app/staticfiles/logo/logo.png 2>/dev/null || echo "⚠️ Could not create logo.png placeholder"
fi

echo ""
echo "=========================================="
echo "✅ Starting ERP-API server on port ${PORT:-4000}"
echo "=========================================="
echo ""

# Start the ASGI server (Daphne)
exec daphne -b 0.0.0.0 -p ${PORT:-4000} ProcureProKEAPI.asgi:application

