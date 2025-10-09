import os
from celery import Celery  # Import Celery directly from the celery package

# Set the default Django settings module
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ProcureProKEAPI.settings')

app = Celery('ProcureProKEAPI')

# Load task modules from all registered Django apps
app.config_from_object('django.conf:settings', namespace='CELERY')

# Auto-discover tasks in all installed apps
app.autodiscover_tasks()