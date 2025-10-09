from .celery import app as celery_app

ADMIN_LABELS = {
    'auth': 'Authentication',  # Example: Change 'auth' to 'Authentication'
    'employee': 'Employee Management',  # Customize as needed
}

__all__ = ('celery_app',)