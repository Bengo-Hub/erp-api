from django.apps import AppConfig


class CampaignsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'crm.campaigns'
    verbose_name = 'CRM Campaigns'
    
    def ready(self):
        """Import signals when the app is ready"""
        try:
            #import crm.campansigns.signals
            pass
        except ImportError as e:
            print(f"Error importing signals: {e}")
            pass
