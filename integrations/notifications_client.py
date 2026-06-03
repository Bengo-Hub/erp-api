"""
Outbound notification client for the decomposed ERP.

The notifications domain now lives in the standalone **notifications-api** service.
The ERP no longer owns templates/providers/delivery; it only *requests* delivery by
emitting domain events to the transactional outbox (``integrations.events``), which
notifications-api consumes:

    subject ``erp.email.requested``        payload = email envelope
    subject ``erp.notification.requested`` payload = multi-channel notification envelope

These two classes are **drop-in replacements** for the old
``notifications.services.EmailService`` / ``NotificationService`` so existing KEEP-app
call sites (HR/payroll, auth, core) keep working by only changing their import to::

    from integrations.notifications_client import EmailService, NotificationService

All methods are best-effort and never raise on transport problems: a delivery request
is durably enqueued in the outbox and drained asynchronously. They return a lightweight
ack dict so callers that inspect the result keep functioning.
"""
from __future__ import annotations

import base64
import logging
from typing import Any, Dict, List, Optional, Union

from .events import publish_event

logger = logging.getLogger(__name__)


def _normalize_attachments(attachments: Optional[List]) -> List[Dict[str, Any]]:
    """Best-effort: turn assorted attachment shapes into JSON-serialisable dicts.

    Supports (filename, bytes[, mimetype]) tuples, dicts with content/path, and bare
    filesystem paths. Binary content is base64-encoded so it survives the event payload.
    Anything unrecognised is skipped (logged) rather than breaking the request.
    """
    out: List[Dict[str, Any]] = []
    for att in attachments or []:
        try:
            if isinstance(att, dict):
                content = att.get("content")
                if isinstance(content, (bytes, bytearray)):
                    att = {**att, "content": base64.b64encode(bytes(content)).decode("ascii"), "encoding": "base64"}
                out.append(att)
            elif isinstance(att, (tuple, list)) and len(att) >= 2:
                filename, content = att[0], att[1]
                mimetype = att[2] if len(att) > 2 else "application/octet-stream"
                if isinstance(content, (bytes, bytearray)):
                    content = base64.b64encode(bytes(content)).decode("ascii")
                out.append({"filename": filename, "content": content, "mimetype": mimetype, "encoding": "base64"})
            elif isinstance(att, str):
                with open(att, "rb") as fh:
                    out.append({
                        "filename": att.rsplit("/", 1)[-1],
                        "content": base64.b64encode(fh.read()).decode("ascii"),
                        "encoding": "base64",
                    })
            else:
                logger.warning("notifications_client: skipping unsupported attachment %r", type(att))
        except Exception:  # pragma: no cover - never let an attachment break delivery
            logger.exception("notifications_client: failed to normalise attachment")
    return out


class EmailService:
    """Drop-in for the removed ``notifications.services.EmailService``.

    ``__init__`` accepts (and ignores) any config args the old service took, so existing
    instantiations such as ``EmailService(config=...)`` keep working.
    """

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.config = kwargs.get("config")

    def send_email(
        self,
        subject: str,
        message: str,
        recipient_list: Union[List[str], str],
        html_message: Optional[str] = None,
        from_email: Optional[str] = None,
        cc: Optional[List[str]] = None,
        bcc: Optional[List[str]] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List] = None,
        async_send: bool = True,
        tenant_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        recipients = [recipient_list] if isinstance(recipient_list, str) else list(recipient_list or [])
        payload = {
            "subject": subject,
            "message": message,
            "recipient_list": recipients,
            "html_message": html_message,
            "from_email": from_email,
            "cc": cc or [],
            "bcc": bcc or [],
            "reply_to": reply_to,
            "attachments": _normalize_attachments(attachments),
        }
        publish_event("email.requested", payload, aggregate_type="erp", tenant_id=tenant_id)
        logger.info("email.requested enqueued -> %s (%s)", recipients, subject)
        return {"status": "queued", "channel": "email", "recipients": recipients}


class NotificationService:
    """Drop-in for the removed ``notifications.services.NotificationService``."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def send_notification(
        self,
        user: Any,
        title: str,
        message: str,
        notification_type: str = "general",
        channels: Optional[List[str]] = None,
        data: Optional[Dict[str, Any]] = None,
        image_url: Optional[str] = None,
        action_url: Optional[str] = None,
        email_subject: Optional[str] = None,
        email_template: Optional[str] = None,
        sms_template: Optional[str] = None,
        push_template: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        async_send: bool = True,
        tenant_id: str = "",
        **kwargs: Any,
    ) -> Dict[str, Any]:
        user_id = getattr(user, "external_id", None) or getattr(user, "id", None) or str(user)
        email = getattr(user, "email", None)
        payload = {
            "user_id": str(user_id) if user_id is not None else None,
            "email": email,
            "title": title,
            "message": message,
            "notification_type": notification_type,
            "channels": channels or ["in_app", "email"],
            "data": data or {},
            "image_url": image_url,
            "action_url": action_url,
            "email_subject": email_subject,
            "templates": {"email": email_template, "sms": sms_template, "push": push_template},
            "context": context or {},
        }
        publish_event("notification.requested", payload, aggregate_type="erp", tenant_id=tenant_id)
        logger.info("notification.requested enqueued -> user=%s (%s)", user_id, notification_type)
        return {"status": "queued", "channels": payload["channels"]}
