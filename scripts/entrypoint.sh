#!/bin/bash
# Entrypoint script for ERP-API service
# Migrations should run in init container (Kubernetes) - this script just starts the server
# For local dev/docker-compose, this script handles migrations as fallback

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

# Quick database connectivity check (should be instant if DB is up)
# Use direct connection test - avoid 'manage.py check' which can fail on unrelated issues
echo "🔌 Checking database connectivity..."
MAX_RETRIES=5
RETRY_COUNT=0

until python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ProcureProKEAPI.settings')
import django
django.setup()
from django.db import connection
connection.ensure_connection()
" 2>/dev/null || [ $RETRY_COUNT -eq $MAX_RETRIES ]; do
  RETRY_COUNT=$((RETRY_COUNT+1))
  echo "⏳ Database not ready yet... (attempt $RETRY_COUNT/$MAX_RETRIES)"
  sleep 2
done

if [ $RETRY_COUNT -eq $MAX_RETRIES ]; then
  echo "❌ Database connection timeout after $MAX_RETRIES attempts"
  echo "📋 Connection error:"
  python -c "
import os
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ProcureProKEAPI.settings')
import django
django.setup()
from django.db import connection
connection.ensure_connection()
" 2>&1 || true
  echo ""
  echo "⚠️ Proceeding to start server anyway..."
else
  echo "✅ Database connected"
fi

# Verify/collect static files (for production)
# Static files should already be collected during Docker build
echo ""
echo "📦 Verifying static files..."
FILE_COUNT=$(find /app/staticfiles -type f 2>/dev/null | wc -l || echo 0)
if [ "$FILE_COUNT" -gt 500 ]; then
    echo "✅ Static files ready: $FILE_COUNT files in /app/staticfiles/"
else
    echo "⚠️ Static files not found in image ($FILE_COUNT files), collecting now..."
    if python manage.py collectstatic --noinput --clear > /dev/null 2>&1; then
        FILE_COUNT=$(find /app/staticfiles -type f 2>/dev/null | wc -l || echo 0)
        echo "✅ Static files collected: $FILE_COUNT files"
    else
        echo "⚠️ Static files collection failed (admin styling may be affected)"
    fi
fi

# Ensure logo files exist
if [ ! -f /app/staticfiles/logo/logo.png ]; then
    mkdir -p /app/staticfiles/logo
    if [ -d /app/static/logo ] && [ -f /app/static/logo/logo.png ]; then
        cp -r /app/static/logo/* /app/staticfiles/logo/ 2>/dev/null && echo "✅ Logo files copied" || true
    fi
fi

echo ""
echo "=========================================="
echo "✅ Starting ERP-API server on port ${PORT:-4000}"
echo "=========================================="
echo ""

# Start the ASGI server (Daphne)
exec daphne -b 0.0.0.0 -p ${PORT:-4000} ProcureProKEAPI.asgi:application
