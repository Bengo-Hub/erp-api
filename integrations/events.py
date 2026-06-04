"""
Event publishing/consuming for the ERP over NATS JetStream.

The ERP uses a transactional outbox: ``publish_event`` writes an ``EventOutbox`` row
inside the caller's DB transaction; the ``drain_outbox`` worker publishes pending rows
to NATS and marks them published. Consumers subscribe to subjects the ERP cares about.

Envelope + subject conventions follow shared-docs/event-architecture.md:
  subject = "{aggregate_type}.{event_type}"  (e.g. "erp.purchase_order.received")
  envelope = {id, tenant_id, aggregate_type, aggregate_id, event_type, payload,
              timestamp, version, source}

``nats-py`` is imported lazily so the app loads even when the dependency or broker is
absent; all publishing is gated by ``settings.EVENTS_ENABLED``.
"""
from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Any, Callable, Iterable, Optional

from django.conf import settings
from django.utils import timezone as dj_timezone

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Publish (outbox)
# ---------------------------------------------------------------------------
def publish_event(
    event_type: str,
    payload: dict[str, Any],
    *,
    aggregate_type: Optional[str] = None,
    aggregate_id: str = "",
    tenant_id: str = "",
) -> Optional["object"]:
    """Enqueue a domain event in the transactional outbox.

    Call inside the same DB transaction as the domain change so the event is only
    sent if the change commits. ``event_type`` is the entity.action suffix
    (e.g. "purchase_order.received"); the full subject becomes
    ``{aggregate_type}.{event_type}``.
    """
    from .models import EventOutbox  # local import to avoid app-loading cycles

    # No-op when events are disabled, otherwise outbox rows accumulate forever with no drainer
    # to publish them. When the pipeline is enabled (prod), rows are written and drained normally.
    if not getattr(settings, "EVENTS_ENABLED", False):
        logger.debug("EVENTS_ENABLED is false; skipping outbox enqueue for %s", event_type)
        return None

    agg = aggregate_type or getattr(settings, "EVENTS_SOURCE_SERVICE", "erp")
    subject = f"{agg}.{event_type}"
    row = EventOutbox.objects.create(
        subject=subject,
        aggregate_type=agg,
        aggregate_id=str(aggregate_id or ""),
        tenant_id=str(tenant_id or ""),
        payload=payload or {},
    )
    logger.debug("Outbox enqueued %s (%s)", subject, row.id)
    return row


def _envelope(row) -> dict[str, Any]:
    # event_type is the subject minus the aggregate prefix
    event_type = row.subject.split(".", 1)[1] if "." in row.subject else row.subject
    return {
        "id": str(row.id),
        "tenant_id": row.tenant_id,
        "aggregate_type": row.aggregate_type,
        "aggregate_id": row.aggregate_id,
        "event_type": event_type,
        "payload": row.payload,
        "timestamp": (row.created_at or datetime.now(timezone.utc)).isoformat(),
        "version": "1.0",
        "source": getattr(settings, "EVENTS_SOURCE_SERVICE", "erp"),
    }


# ---------------------------------------------------------------------------
# NATS connection helpers (lazy import)
# ---------------------------------------------------------------------------
async def _connect():
    import nats  # lazy

    nc = await nats.connect(
        getattr(settings, "EVENTS_NATS_URL", "nats://localhost:4222"),
        name=getattr(settings, "EVENTS_SOURCE_SERVICE", "erp"),
        max_reconnect_attempts=-1,
    )
    return nc


# ---------------------------------------------------------------------------
# Drain worker
# ---------------------------------------------------------------------------
async def _drain_async(batch_size: int) -> int:
    from asgiref.sync import sync_to_async
    from .models import EventOutbox

    pending = await sync_to_async(list)(
        EventOutbox.objects.filter(status=EventOutbox.STATUS_PENDING).order_by("created_at")[:batch_size]
    )
    if not pending:
        return 0

    nc = await _connect()
    js = nc.jetstream()
    published = 0
    try:
        for row in pending:
            try:
                await js.publish(row.subject, json.dumps(_envelope(row)).encode())
                row.status = EventOutbox.STATUS_PUBLISHED
                row.published_at = dj_timezone.now()
                row.error = ""
            except Exception as exc:  # keep draining the rest
                row.attempts += 1
                row.error = str(exc)
                if row.attempts >= getattr(settings, "EVENTS_MAX_ATTEMPTS", 10):
                    row.status = EventOutbox.STATUS_FAILED
                logger.warning("Outbox publish failed for %s: %s", row.subject, exc)
            await sync_to_async(row.save)(
                update_fields=["status", "published_at", "attempts", "error"]
            )
            if row.status == EventOutbox.STATUS_PUBLISHED:
                published += 1
    finally:
        await nc.drain()
    return published


def drain_outbox(batch_size: int = 200) -> int:
    """Publish pending outbox rows to NATS. Returns the count published."""
    if not getattr(settings, "EVENTS_ENABLED", False):
        logger.info("EVENTS_ENABLED is false; skipping outbox drain.")
        return 0
    return asyncio.run(_drain_async(batch_size))


# ---------------------------------------------------------------------------
# Consumer
# ---------------------------------------------------------------------------
async def _consume_async(handlers: dict[str, Callable[[dict], None]], durable_prefix: str):
    from asgiref.sync import sync_to_async

    nc = await _connect()
    js = nc.jetstream()

    async def _make_cb(handler):
        async def cb(msg):
            try:
                data = json.loads(msg.data.decode())
                await sync_to_async(handler)(data)
                await msg.ack()
            except Exception as exc:
                logger.exception("Consumer handler error on %s: %s", msg.subject, exc)
        return cb

    for subject, handler in handlers.items():
        durable = f"{durable_prefix}-{subject.replace('.', '-').replace('*', 'all').replace('>', 'all')}"
        await js.subscribe(subject, durable=durable, cb=await _make_cb(handler), manual_ack=True)
        logger.info("Subscribed to %s (durable=%s)", subject, durable)

    # Block forever; cancelled on process shutdown.
    while True:
        await asyncio.sleep(3600)


def run_consumers(handlers: dict[str, Callable[[dict], None]], durable_prefix: str = "erp") -> None:
    """Run NATS consumers for the given {subject: handler} map (blocking)."""
    if not getattr(settings, "EVENTS_ENABLED", False):
        logger.info("EVENTS_ENABLED is false; not starting consumers.")
        return
    asyncio.run(_consume_async(handlers, durable_prefix))


# Registry of subjects the ERP consumes. Per-module integrations append handlers here
# (e.g. treasury.payment.succeeded, inventory.stock.low) as domains are migrated.
CONSUMER_HANDLERS: dict[str, Callable[[dict], None]] = {}
