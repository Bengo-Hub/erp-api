from django.apps import AppConfig


class AssetsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'assets'
    
    def ready(self):
        # Import signals for auto-asset creation
        import assets.signals