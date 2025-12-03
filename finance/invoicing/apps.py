from django.apps import AppConfig


class InvoicingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'finance.invoicing'
    verbose_name = 'Invoicing'
    
    def ready(self):
        # Import signals for inventory integration
        import finance.invoicing.signals
