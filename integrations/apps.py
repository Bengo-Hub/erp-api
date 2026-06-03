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

        # Payroll disbursement confirmation from treasury (WS4).
        try:
            from hrm.payroll.treasury_integration import handle_payroll_disbursed
            CONSUMER_HANDLERS.setdefault("treasury.payroll.disbursed", handle_payroll_disbursed)
        except Exception:  # hrm import issues should never block app startup
            pass
