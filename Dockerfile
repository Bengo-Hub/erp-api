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
    && rm -rf /var/lib/apt/lists/*

FROM base AS deps
COPY requirements.txt .
RUN python -m pip install --upgrade pip \
    && pip install -r requirements.txt

FROM base AS source
WORKDIR /app
COPY . .

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
    DJANGO_ENV=production

# Static dir (optional)
RUN mkdir -p /app/staticfiles && chown -R appuser:appgroup /app

USER appuser

EXPOSE 4000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s --retries=3 CMD curl -fsS http://localhost:${PORT}/api/v1/core/health/ || exit 1

CMD ["bash","-lc","python manage.py collectstatic --noinput || true && gunicorn ProcureProKEAPI.wsgi:application --bind 0.0.0.0:${PORT} --workers 3 --timeout 120"]


