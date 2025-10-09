from django.apps import AppConfig


class ManufacturingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'manufacturing'
    verbose_name = 'Manufacturing Management'

    def ready(self):
        import manufacturing.signals
