"""
Approval utility functions for use across the application.
"""
from django.contrib.contenttypes.models import ContentType
from django.db import models
from .models import Approval, ApprovalRequest


def get_current_approver_id(obj):
    """
    Get the current approver ID for an object in the approval workflow.

    Returns the ID of the user who is the current pending approver for this object,
    or None if there's no pending approval.

    Args:
        obj: Any model instance that can be used in the approval workflow

    Returns:
        int or None: The user ID of the current approver, or None
    """
    if obj is None:
        return None

    try:
        content_type = ContentType.objects.get_for_model(obj)

        # Find the first pending approval for this object (ordered by step_number)
        pending_approval = Approval.objects.filter(
            content_type=content_type,
            object_id=obj.pk,
            status='pending'
        ).select_related('step').order_by('step__step_number').first()

        if pending_approval and pending_approval.approver_id:
            return pending_approval.approver_id

    except Exception:
        pass

    return None


def get_pending_approvals_for_object(obj):
    """
    Get all pending approvals for an object.

    Args:
        obj: Any model instance that can be used in the approval workflow

    Returns:
        list: List of dicts with approver_id and step info
    """
    if obj is None:
        return []

    try:
        content_type = ContentType.objects.get_for_model(obj)

        pending_approvals = Approval.objects.filter(
            content_type=content_type,
            object_id=obj.pk,
            status='pending'
        ).select_related('step').order_by('step__step_number')

        return [
            {
                'approver_id': a.approver_id,
                'step_name': a.step.name if a.step else None,
                'step_number': a.step.step_number if a.step else None,
            }
            for a in pending_approvals
        ]

    except Exception:
        return []


def get_approval_request_for_object(obj):
    """
    Get the approval request for an object if one exists.

    Args:
        obj: Any model instance that can be used in the approval workflow

    Returns:
        ApprovalRequest or None
    """
    if obj is None:
        return None

    try:
        content_type = ContentType.objects.get_for_model(obj)
        return ApprovalRequest.objects.filter(
            content_type=content_type,
            object_id=obj.pk
        ).first()
    except Exception:
        return None


def can_user_approve(user, obj):
    """
    Check if a user can approve the given object.

    Args:
        user: User instance
        obj: Any model instance that can be used in the approval workflow

    Returns:
        bool: True if user can approve this object
    """
    if user is None or obj is None:
        return False

    current_approver_id = get_current_approver_id(obj)
    return current_approver_id == user.pk


def get_approvers_for_permission(permission_codename):
    """
    Get users who have a specific permission.

    Args:
        permission_codename: The permission codename (e.g., 'procurement.view_procurementrequest')

    Returns:
        list: List of User instances who have the permission
    """
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission

    User = get_user_model()

    try:
        # Parse permission codename
        if '.' in permission_codename:
            app_label, codename = permission_codename.split('.', 1)
        else:
            codename = permission_codename
            app_label = None

        # Get the permission
        perm_filter = {'codename': codename}
        if app_label:
            perm_filter['content_type__app_label'] = app_label

        try:
            permission = Permission.objects.get(**perm_filter)
        except Permission.DoesNotExist:
            return []

        # Get users with this permission directly or through groups
        users_with_perm = User.objects.filter(
            is_active=True
        ).filter(
            models.Q(user_permissions=permission) |
            models.Q(groups__permissions=permission) |
            models.Q(is_superuser=True)
        ).distinct()

        return list(users_with_perm)

    except Exception:
        return []


class ApprovalSerializerMixin:
    """
    Mixin for serializers to add approval-related fields.

    Add this mixin to your serializer and include 'current_approver_id' and
    'pending_approvals' in your fields list.
    """

    def get_current_approver_id(self, obj):
        """Get the current approver ID for this object."""
        return get_current_approver_id(obj)

    def get_pending_approvals(self, obj):
        """Get pending approvals for this object."""
        return get_pending_approvals_for_object(obj)

    def get_approval_request(self, obj):
        """Get the approval request info for this object."""
        request = get_approval_request_for_object(obj)
        if request:
            return {
                'id': request.id,
                'status': request.status,
                'current_approver_id': get_current_approver_id(obj),
                'workflow_id': request.workflow_id,
            }
        return None
