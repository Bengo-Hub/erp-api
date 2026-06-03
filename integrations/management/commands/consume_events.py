"""Run NATS JetStream consumers for subjects the ERP subscribes to.

Handlers are registered in ``integrations.events.CONSUMER_HANDLERS`` by per-module
integrations as domains are migrated (e.g. treasury.payment.succeeded). This command
blocks, processing messages until terminated.

    python manage.py consume_events
"""
from django.core.management.base import BaseCommand

from integrations.events import CONSUMER_HANDLERS, run_consumers


class Command(BaseCommand):
    help = "Run NATS event consumers for the ERP."

    def handle(self, *args, **opts):
        if not CONSUMER_HANDLERS:
            self.stdout.write(self.style.WARNING("No consumer handlers registered; nothing to do."))
            return
        self.stdout.write(self.style.SUCCESS(
            f"Starting consumers for: {', '.join(CONSUMER_HANDLERS)}"
        ))
        run_consumers(CONSUMER_HANDLERS)
