from django.apps import AppConfig


class OrderConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ecommerce.order'
    label = 'order'  # This ensures the app_label is just 'order', not 'ecommerce.order'
    
    def ready(self):
        # Import signals for their side effects (signal registration)
        # This is intentional, so we can ignore the lint warning
        import ecommerce.order.signals  # noqa
