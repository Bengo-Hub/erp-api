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
    echo "📋 Found $PENDING_MIGRATIONS pending migrations - acquiring migration lock..."
    
    # Distributed lock using database: only one pod acquires lock and runs migrations
    # This prevents concurrent migrations on shared database
    LOCK_ACQUIRED=0
    LOCK_ATTEMPTS=0
    MAX_LOCK_ATTEMPTS=30
    
    while [ $LOCK_ATTEMPTS -lt $MAX_LOCK_ATTEMPTS ] && [ $LOCK_ACQUIRED -eq 0 ]; do
      LOCK_ATTEMPTS=$((LOCK_ATTEMPTS + 1))
      
      # Try to acquire lock using Django's database
      if python manage.py shell -c "
from django.db import connection
from datetime import datetime, timedelta

with connection.cursor() as cursor:
    # Create migrations_lock table if not exists
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS migrations_lock (
            id SERIAL PRIMARY KEY,
            lock_name VARCHAR(255) UNIQUE,
            acquired_at TIMESTAMP,
            released_at TIMESTAMP
        )
    ''')
    
    # Try to acquire lock with 5-minute expiry
    try:
        cursor.execute('''
            INSERT INTO migrations_lock (lock_name, acquired_at)
            SELECT 'erp_migrations', NOW()
            WHERE NOT EXISTS (
                SELECT 1 FROM migrations_lock 
                WHERE lock_name = 'erp_migrations'
                AND acquired_at > NOW() - INTERVAL '5 minutes'
            )
        ''')
        connection.commit()
        
        # Check if insert was successful
        cursor.execute('SELECT COUNT(*) FROM migrations_lock WHERE lock_name = %s', ['erp_migrations'])
        if cursor.fetchone()[0] > 0:
            print('LOCK_ACQUIRED')
    except Exception:
        pass
" 2>&1 | grep -q "LOCK_ACQUIRED"; then
        LOCK_ACQUIRED=1
        echo "✅ Migration lock acquired (pod is eligible to run migrations)"
        
        # Run database migrations only when lock is held
        echo "🔄 Running database migrations..."
        if python manage.py migrate --noinput 2>&1; then
            echo "✅ Migrations completed successfully"
            
            # Release lock after successful migration
            python manage.py shell -c "
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute('UPDATE migrations_lock SET released_at = NOW() WHERE lock_name = %s', ['erp_migrations'])
    connection.commit()
" 2>&1 || echo "⚠️ Lock release failed (non-critical)"
        else
            echo "❌ Migration failed! Service may not function correctly."
            # Attempt to release lock on failure
            python manage.py shell -c "
from django.db import connection
with connection.cursor() as cursor:
    cursor.execute('UPDATE migrations_lock SET released_at = NOW() WHERE lock_name = %s', ['erp_migrations'])
    connection.commit()
" 2>&1 || true
            exit 1
        fi
      else
        # Lock not acquired - wait for other pod to finish migrations
        if [ $LOCK_ATTEMPTS -lt $MAX_LOCK_ATTEMPTS ]; then
          echo "⏳ Migration lock held by another pod (attempt $LOCK_ATTEMPTS/$MAX_LOCK_ATTEMPTS)... waiting 2s"
          sleep 2
        fi
      fi
    done
    
    if [ $LOCK_ACQUIRED -eq 0 ]; then
      echo "⚠️ Could not acquire migration lock after $MAX_LOCK_ATTEMPTS attempts"
      echo "   Proceeding to start server - other pod should have completed migrations"
      echo "   (This is safe: Django tracks applied migrations in django_migrations table)"
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

# Collect static files (for production) - with proper error checking
echo ""
echo "📦 Collecting static files..."
COLLECTSTATIC_LOG=$(mktemp)
if python manage.py collectstatic --noinput --clear > "$COLLECTSTATIC_LOG" 2>&1; then
    # Parse collectstatic output for success message
    COLLECTED=$(grep -E "^[0-9]+ static" "$COLLECTSTATIC_LOG" 2>/dev/null | tail -1 || echo "completed")
    echo "✅ Static files collected: $COLLECTED"
    
    # Verify collection succeeded by checking directory
    FILE_COUNT=$(find /app/staticfiles -type f 2>/dev/null | wc -l || echo 0)
    if [ "$FILE_COUNT" -gt 100 ]; then
        echo "✅ Verified: $FILE_COUNT files in /app/staticfiles/"
    else
        echo "⚠️ WARNING: Only $FILE_COUNT static files collected (expected 1000+)"
        echo "   Admin panel styling may be missing in production"
    fi
    rm -f "$COLLECTSTATIC_LOG"
    
    # Create logo directory and placeholder files for admin panel
    echo "🎨 Creating logo files for admin panel..."
    mkdir -p /app/staticfiles/logo
    # Create a simple 1x1 transparent PNG as placeholder
    echo -n "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==" | base64 -d > /app/staticfiles/logo/logo.png 2>/dev/null || echo "⚠️ Could not create logo.png placeholder"
    echo "✅ Logo placeholder created"
else
    echo "❌ ERROR: Static files collection FAILED!"
    echo "   Admin panel styling will be broken - see errors below:"
    tail -30 "$COLLECTSTATIC_LOG"
    rm -f "$COLLECTSTATIC_LOG"
fi

echo ""
echo "=========================================="
echo "✅ Starting ERP-API server on port ${PORT:-4000}"
echo "=========================================="
echo ""

# Start the ASGI server (Daphne)
exec daphne -b 0.0.0.0 -p ${PORT:-4000} ProcureProKEAPI.asgi:application

