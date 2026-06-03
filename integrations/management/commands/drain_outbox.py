"""Publish pending EventOutbox rows to NATS JetStream.

Run as a loop (worker) or one-shot (e.g. from Celery beat):
    python manage.py drain_outbox --loop --interval 5
    python manage.py drain_outbox            # one pass
"""
import time

from django.core.management.base import BaseCommand

from integrations.events import drain_outbox


class Command(BaseCommand):
    help = "Drain the event outbox to NATS JetStream."

    def add_arguments(self, parser):
        parser.add_argument("--loop", action="store_true", help="Run continuously.")
        parser.add_argument("--interval", type=float, default=5.0, help="Seconds between passes in loop mode.")
        parser.add_argument("--batch-size", type=int, default=200)

    def handle(self, *args, **opts):
        if opts["loop"]:
            self.stdout.write(self.style.SUCCESS("Outbox drain loop started."))
            while True:
                count = drain_outbox(opts["batch_size"])
                if count:
                    self.stdout.write(f"Published {count} event(s).")
                time.sleep(opts["interval"])
        else:
            count = drain_outbox(opts["batch_size"])
            self.stdout.write(self.style.SUCCESS(f"Published {count} event(s)."))
