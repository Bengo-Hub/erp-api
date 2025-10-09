from django.apps import AppConfig


class StockinventoryConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'ecommerce.stockinventory'

    def ready(self):
        # Import signals and connect them here
        import ecommerce.stockinventory.signals 
