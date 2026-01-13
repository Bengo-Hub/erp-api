# Multi-stage Dockerfile for Django ERP API

FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# System deps
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
        libpq-dev \
        gcc \
        libcairo2-dev \
        libpango1.0-dev \
        libglib2.0-dev \
        libffi-dev \
        libjpeg-dev \
        libpng-dev \
        pkg-config \
        cmake \
        git \
        libxml2-dev \
        libxslt-dev \
    && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY requirements.txt .
RUN python -m pip install --upgrade pip setuptools wheel \
    && pip install -r requirements.txt

FROM base AS source
WORKDIR /app
COPY . .

# Collect static files during build (CRITICAL for WhiteNoise manifest)
# WhiteNoise needs the staticfiles.json manifest generated at build time
# This includes Django admin, DRF, Jazzmin, and all app static files
COPY --from=deps /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=deps /usr/local/bin /usr/local/bin
ENV DJANGO_SETTINGS_MODULE=ProcureProKEAPI.settings

# Verify static directory exists and collect static files
# Use SQLite file database to bypass real database connection during collectstatic
# Also set DEBUG=False to use production static storage (WhiteNoise CompressedManifest)
RUN echo "=== Static Files Collection ===" \
    && echo "Static source directories:" && ls -la /app/static/ 2>/dev/null || echo "No /app/static/ directory" \
    && mkdir -p /app/staticfiles \
    && DATABASE_URL="sqlite:///tmp/build.sqlite3" DEBUG=False python manage.py collectstatic --noinput --clear 2>&1 \
    && rm -f /tmp/build.sqlite3 \
    && echo "=== Static files collected ===" \
    && ls -la /app/staticfiles/ \
    && echo "=== Logo files ===" && ls -la /app/staticfiles/logo/ 2>/dev/null || echo "Warning: No logo directory in staticfiles" \
    && echo "=== Manifest file ===" && ls -la /app/staticfiles/staticfiles.json 2>/dev/null || echo "Warning: No manifest file" \
    && echo "=== File count ===" && find /app/staticfiles -type f | wc -l

FROM base AS runtime
WORKDIR /app

# Non-root user
RUN addgroup --system appgroup && adduser --system --ingroup appgroup appuser

# Copy Python packages (cached layer)
COPY --from=deps /usr/local/lib/python3.11 /usr/local/lib/python3.11
COPY --from=deps /usr/local/bin /usr/local/bin

# Copy source code
COPY --from=source /app .

# Environment defaults
ENV DJANGO_SETTINGS_MODULE=ProcureProKEAPI.settings \
    PYTHONPATH=/app \
    PORT=4000 \
    DJANGO_ENV=production \
    DEBUG=False

# Create media directories with proper permissions
# Static files are pre-collected in the image during build (WhiteNoise serves them)
# Media files should be persisted via PersistentVolume in production
RUN mkdir -p /app/staticfiles \
    && mkdir -p /app/media/business/logo \
    && mkdir -p /app/media/invoices \
    && mkdir -p /app/media/receipts \
    && mkdir -p /app/media/reports \
    && mkdir -p /app/media/uploads \
    && chown -R appuser:appgroup /app/staticfiles /app/media \
    && chmod -R 755 /app/media

USER appuser

# Volume mount point for media uploads (use PVC in k8s)
VOLUME ["/app/media"]

EXPOSE 4000

HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 CMD curl -fsS http://localhost:${PORT}/api/v1/core/health/ || exit 1

# Copy startup scripts
COPY scripts/init-media.sh /usr/local/bin/init-media.sh
COPY scripts/entrypoint.sh /usr/local/bin/entrypoint.sh
USER root
RUN chmod +x /usr/local/bin/init-media.sh /usr/local/bin/entrypoint.sh
USER appuser

# Use entrypoint script that runs migrations automatically on every container start
CMD ["/usr/local/bin/entrypoint.sh"]