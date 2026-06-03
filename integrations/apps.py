from django.apps import AppConfig


class IntegrationsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'integrations'

    def ready(self):
        """Register NATS consumer handlers for subjects the ERP subscribes to.

        auth.* events keep the local tenant/outlet shadows in sync (auth-api is the
        source of truth). Handlers are looked up by subject in consume_events.
        """
        from .events import CONSUMER_HANDLERS
        from .tenant_sync import handle_tenant_event, handle_outlet_event

        CONSUMER_HANDLERS.setdefault("auth.tenant.>", handle_tenant_event)
        CONSUMER_HANDLERS.setdefault("auth.outlet.>", handle_outlet_event)
