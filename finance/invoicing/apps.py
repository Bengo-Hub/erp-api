from django.apps import AppConfig


class InvoicingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finance.invoicing'
    verbose_name = 'Invoicing'
    
    def ready(self):
        # Import signals for inventory integration
        # Import signal handlers
        try:
            from . import signals  # noqa: F401
        except Exception:
            pass
