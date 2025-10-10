"""
Custom Prometheus metrics for BengoERP API
"""
import time
import psutil
from functools import wraps

from prometheus_client import Counter, Histogram, Gauge, Info
from django_prometheus.utils import PowersOfTenFormatter
from django.db import connection
from django.conf import settings


# Application Info
app_info = Info('bengoerp_api_info', 'BengoERP API Information')
app_info.info({
    'version': getattr(settings, 'APP_VERSION', '1.0.0'),
    'environment': getattr(settings, 'ENVIRONMENT', 'production')
})

# Request metrics
REQUEST_COUNT = Counter(
    'bengoerp_api_requests_total',
    'Total number of API requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_DURATION = Histogram(
    'bengoerp_api_request_duration_seconds',
    'API request duration in seconds',
    ['method', 'endpoint'],
    buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
)

# Database metrics
DB_CONNECTIONS = Gauge(
    'bengoerp_api_db_connections',
    'Number of active database connections'
)

DB_QUERY_DURATION = Histogram(
    'bengoerp_api_db_query_duration_seconds',
    'Database query duration in seconds',
    ['query_type'],
    buckets=(0.001, 0.01, 0.1, 0.5, 1.0, 2.0, 5.0)
)

# Business metrics
ACTIVE_USERS = Gauge(
    'bengoerp_api_active_users',
    'Number of currently active users'
)

API_ERRORS = Counter(
    'bengoerp_api_errors_total',
    'Total number of API errors',
    ['error_type', 'endpoint']
)

# System metrics
SYSTEM_CPU_USAGE = Gauge(
    'bengoerp_api_system_cpu_usage',
    'System CPU usage percentage'
)

SYSTEM_MEMORY_USAGE = Gauge(
    'bengoerp_api_system_memory_usage',
    'System memory usage percentage'
)

def track_request_duration():
    """Decorator to track API request duration"""
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            start_time = time.time()

            # Extract endpoint info
            endpoint = request.path
            method = request.method

            try:
                response = func(request, *args, **kwargs)
                status_code = getattr(response, 'status_code', 200)

                # Record metrics
                REQUEST_COUNT.labels(
                    method=method,
                    endpoint=endpoint,
                    status_code=status_code
                ).inc()

                REQUEST_DURATION.labels(
                    method=method,
                    endpoint=endpoint
                ).observe(time.time() - start_time)

                return response

            except Exception as e:
                # Record error metrics
                status_code = 500
                REQUEST_COUNT.labels(
                    method=method,
                    endpoint=endpoint,
                    status_code=status_code
                ).inc()

                API_ERRORS.labels(
                    error_type=type(e).__name__,
                    endpoint=endpoint
                ).inc()

                raise

        return wrapper
    return decorator


def track_db_query(query_type='unknown'):
    """Decorator to track database query performance"""
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            start_time = time.time()

            try:
                result = func(*args, **kwargs)

                DB_QUERY_DURATION.labels(
                    query_type=query_type
                ).observe(time.time() - start_time)

                return result

            except Exception as e:
                # Record query error
                DB_QUERY_DURATION.labels(
                    query_type=f"{query_type}_error"
                ).observe(time.time() - start_time)

                raise

        return wrapper
    return decorator


def update_system_metrics():
    """Update system-level metrics"""
    try:
        # CPU usage
        cpu_percent = psutil.cpu_percent(interval=1)
        SYSTEM_CPU_USAGE.set(cpu_percent / 100.0)

        # Memory usage
        memory = psutil.virtual_memory()
        SYSTEM_MEMORY_USAGE.set(memory.percent / 100.0)

        # Database connections
        DB_CONNECTIONS.set(len(connection.cursor().execute("SELECT 1").fetchall()))

    except Exception:
        # Silently handle metrics collection errors
        pass


def record_business_metric(metric_name, value, labels=None):
    """Record custom business metrics"""
    # This is a placeholder for recording business-specific metrics
    # In a real implementation, you'd want to create specific metrics for:
    # - User activity
    # - Transaction volume
    # - System load
    # - Custom KPIs
    pass


# Celery task metrics (if using Celery)
CELERY_TASKS_STARTED = Counter(
    'bengoerp_api_celery_tasks_started_total',
    'Total number of Celery tasks started',
    ['task_name']
)

CELERY_TASKS_COMPLETED = Counter(
    'bengoerp_api_celery_tasks_completed_total',
    'Total number of Celery tasks completed',
    ['task_name', 'status']
)

CELERY_TASK_DURATION = Histogram(
    'bengoerp_api_celery_task_duration_seconds',
    'Celery task duration in seconds',
    ['task_name'],
    buckets=(0.1, 1.0, 10.0, 60.0, 300.0, 600.0)
)
