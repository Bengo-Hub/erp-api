"""
Thin, optional integration layer for wiring domain objects (appraisals,
performance reviews, recruitment offers, ...) into the centralized approvals
app without coupling the domain viewsets to its internals.

Design goals (per feedback_workflow_rules / keep-it-modular):
  * NON-INTRUSIVE: if no ApprovalWorkflow is configured for a workflow_type the
    helpers are no-ops and the caller's existing direct status update remains the
    single source of truth (fallback must never break).
  * IDEMPOTENT-ish: start_approval reuses an existing ApprovalRequest for the
    object instead of creating duplicates.
  * RESILIENT: any failure in the approvals plumbing is swallowed and logged so a
    misconfigured workflow can never block a domain approve/reject.

Public API:
  start_approval(obj, workflow_type, requested_by, title=None, amount=None)
  record_decision(obj, user, approved, notes=None)
"""
from __future__ import annotations

import logging
from typing import Optional

from django.contrib.contenttypes.models import ContentType
from django.utils import timezone

logger = logging.getLogger(__name__)


def _get_active_workflow(workflow_type: str):
    """Return the active ApprovalWorkflow for a type, or None if not configured."""
    from .models import ApprovalWorkflow
    return (
        ApprovalWorkflow.objects.filter(workflow_type=workflow_type, is_active=True)
        .order_by("id")
        .first()
    )


def get_request_for_object(obj):
    """Return the existing ApprovalRequest for ``obj`` or None (reuses utils)."""
    try:
        from .utils import get_approval_request_for_object
        return get_approval_request_for_object(obj)
    except Exception:  # pragma: no cover - defensive
        return None


def start_approval(
    obj,
    workflow_type: str,
    requested_by,
    title: Optional[str] = None,
    amount=None,
):
    """
    Create (and submit) an ApprovalRequest for ``obj`` when a workflow is
    configured for ``workflow_type``.

    Returns the ApprovalRequest if one was created/exists, else None. Never
    raises: callers keep their direct status update as the fallback.
    """
    if obj is None or requested_by is None:
        return None

    workflow = _get_active_workflow(workflow_type)
    if workflow is None:
        # No workflow configured -> no-op, caller falls back to direct status.
        return None

    try:
        from .models import ApprovalRequest

        existing = get_request_for_object(obj)
        if existing is not None:
            return existing

        content_type = ContentType.objects.get_for_model(obj)
        request = ApprovalRequest.objects.create(
            content_type=content_type,
            object_id=obj.pk,
            workflow=workflow,
            requester=requested_by,
            title=title or f"{workflow.get_workflow_type_display()} #{obj.pk}",
            amount=amount,
        )
        # Move it out of draft so approvers/steps are generated.
        try:
            request.submit()
        except Exception:  # pragma: no cover - submit is best-effort
            logger.exception("approvals.integration: submit() failed for %s", obj)
        return request
    except Exception:
        logger.exception(
            "approvals.integration: start_approval failed (type=%s, obj=%s)",
            workflow_type,
            getattr(obj, "pk", None),
        )
        return None


def record_decision(obj, user, approved: bool, notes: Optional[str] = None):
    """
    Reflect a domain approve/reject decision onto the object's ApprovalRequest
    (and its pending Approval rows) when one exists.

    No-op (returns None) when there is no ApprovalRequest, so domain code that
    only does a direct status update continues to work unchanged. Never raises.
    """
    if obj is None:
        return None

    request = get_request_for_object(obj)
    if request is None:
        return None

    try:
        from .models import Approval

        # Resolve any pending approval rows for this object and stamp them with
        # the deciding user so the audit trail is consistent.
        content_type = ContentType.objects.get_for_model(obj)
        pending = Approval.objects.filter(
            content_type=content_type,
            object_id=obj.pk,
            status="pending",
        )
        for approval in pending:
            if approved:
                approval.approver = approval.approver or user
                approval.approve(notes=notes)
            else:
                approval.approver = approval.approver or user
                approval.reject(notes=notes)

        # Update the request envelope.
        if approved:
            # request.approve() requires 'in_progress'; force it for the simple
            # single-decision case used by HR domain objects.
            request.status = "approved"
            request.approved_at = timezone.now()
            request.save(update_fields=["status", "approved_at", "updated_at"])
        else:
            request.status = "rejected"
            request.rejected_at = timezone.now()
            request.save(update_fields=["status", "rejected_at", "updated_at"])
        return request
    except Exception:
        logger.exception(
            "approvals.integration: record_decision failed (obj=%s, approved=%s)",
            getattr(obj, "pk", None),
            approved,
        )
        return None
