"""Run NATS JetStream consumers for subjects the ERP subscribes to.

Handlers are registered in ``integrations.events.CONSUMER_HANDLERS`` by per-module
integrations as domains are migrated (e.g. treasury.payment.succeeded). This command
blocks, processing messages until terminated.

    python manage.py consume_events
"""
import time

from django.conf import settings
from django.core.management.base import BaseCommand

from integrations.events import CONSUMER_HANDLERS, run_consumers


class Command(BaseCommand):
    help = "Run NATS event consumers for the ERP (auto-restarts on transient failures)."

    def add_arguments(self, parser):
        parser.add_argument("--max-backoff", type=int, default=60,
                            help="Maximum seconds to wait between restart attempts.")

    def handle(self, *args, **opts):
        if not getattr(settings, "EVENTS_ENABLED", False):
            self.stdout.write(self.style.WARNING("EVENTS_ENABLED is false; consumers not started."))
            return
        if not CONSUMER_HANDLERS:
            self.stdout.write(self.style.WARNING("No consumer handlers registered; nothing to do."))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Starting consumers for: {', '.join(CONSUMER_HANDLERS)}"
        ))
        max_backoff = max(1, opts.get("max_backoff", 60))
        backoff = 1
        while True:
            try:
                run_consumers(CONSUMER_HANDLERS)
                # run_consumers blocks forever; returning means a clean shutdown was requested.
                return
            except KeyboardInterrupt:
                self.stdout.write(self.style.WARNING("Consumer interrupted; shutting down."))
                return
            except Exception as exc:  # transient broker/connection failure — restart with backoff
                self.stderr.write(self.style.ERROR(f"Consumer crashed: {exc}; restarting in {backoff}s"))
                time.sleep(backoff)
                backoff = min(max_backoff, backoff * 2)
