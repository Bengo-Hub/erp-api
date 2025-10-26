"""
Centralized Audit Logging System

Provides automatic audit trail tracking for all business-critical operations including:
- User who performed the action
- Timestamp of the action
- What was changed (before/after)
- Reason/notes for the change
- IP address and user agent
"""

import logging
from functools import wraps
from typing import Any, Dict, Optional, Callable
from django.utils import timezone
from django.contrib.auth import get_user_model
import json

logger = logging.getLogger(__name__)
User = get_user_model()


class AuditTrail:
    """
    Audit trail tracking system for recording business operations.
    """
    
    # Operation types
    CREATE = 'CREATE'
    UPDATE = 'UPDATE'
    DELETE = 'DELETE'
    PAYMENT = 'PAYMENT'
    APPROVAL = 'APPROVAL'
    TRANSFER = 'TRANSFER'
    EXPORT = 'EXPORT'
    SUBMIT = 'SUBMIT'
    CANCEL = 'CANCEL'
    REVERSE = 'REVERSE'
    VIEW = 'VIEW'
    
    OPERATION_TYPES = [CREATE, UPDATE, DELETE, PAYMENT, APPROVAL, TRANSFER, EXPORT, SUBMIT, CANCEL, REVERSE, VIEW]
    
    @staticmethod
    def log(
        operation: str,
        module: str,
        entity_type: str,
        entity_id: Any,
        user: Optional[User] = None,
        changes: Optional[Dict[str, Any]] = None,
        reason: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        request=None,
    ) -> Dict[str, Any]:
        """
        Log an audit trail entry.
        
        Args:
            operation: Type of operation (CREATE, UPDATE, DELETE, PAYMENT, etc.)
            module: Module name (e.g., 'finance', 'hrm', 'ecommerce')
            entity_type: Type of entity (e.g., 'Invoice', 'Employee', 'Payslip')
            entity_id: ID of the entity being operated on
            user: User performing the operation
            changes: Dictionary of changes {field: {old: value, new: value}}
            reason: Reason/notes for the operation
            ip_address: Client IP address
            user_agent: Client user agent
            request: Django request object (extracts IP and user agent if provided)
        
        Returns:
            dict: Audit log record
        
        Example:
            AuditTrail.log(
                operation=AuditTrail.PAYMENT,
                module='finance',
                entity_type='Invoice',
                entity_id=123,
                user=request.user,
                changes={'status': {'old': 'pending', 'new': 'paid'}},
                reason='Customer paid via M-Pesa',
                request=request
            )
        """
        try:
            # Extract info from request if provided
            if request:
                if not user:
                    user = request.user if request.user.is_authenticated else None
                if not ip_address:
                    ip_address = AuditTrail._get_client_ip(request)
                if not user_agent:
                    user_agent = request.META.get('HTTP_USER_AGENT', '')
            
            # Build audit record
            audit_record = {
                'timestamp': timezone.now().isoformat(),
                'operation': operation,
                'module': module,
                'entity_type': entity_type,
                'entity_id': str(entity_id),
                'user_id': user.id if user else None,
                'username': user.username if user else 'system',
                'changes': changes or {},
                'reason': reason,
                'ip_address': ip_address,
                'user_agent': user_agent,
            }
            
            # Log to audit logger
            logger.info(
                f"AUDIT: {operation} {entity_type}#{entity_id} by {user.username if user else 'system'}",
                extra={'audit': audit_record}
            )
            
            return audit_record
            
        except Exception as e:
            logger.error(f"Error logging audit trail: {str(e)}", exc_info=True)
            return {}
    
    @staticmethod
    def _get_client_ip(request) -> str:
        """Extract client IP address from request."""
        x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
        if x_forwarded_for:
            ip = x_forwarded_for.split(',')[0]
        else:
            ip = request.META.get('REMOTE_ADDR')
        return ip


def audit_log(
    operation: str,
    module: str,
    entity_type: str,
    entity_id_field: str = 'pk',
    extract_changes: Optional[Callable] = None
):
    """
    Decorator to automatically log audit trail for functions/methods.
    
    Args:
        operation: Type of operation (CREATE, UPDATE, DELETE, etc.)
        module: Module name
        entity_type: Type of entity
        entity_id_field: Field/attribute name containing entity ID (default: 'pk')
        extract_changes: Optional callable to extract changes from function args
    
    Usage:
        @audit_log(
            operation=AuditTrail.PAYMENT,
            module='finance',
            entity_type='Invoice',
            entity_id_field='id'
        )
        def process_payment(invoice_id, amount, method, user):
            # Process payment
            pass
    
    Example with change extraction:
        def extract_payment_changes(old_instance, new_instance):
            return {
                'status': {'old': old_instance.status, 'new': new_instance.status},
                'amount_paid': {'old': old_instance.amount_paid, 'new': new_instance.amount_paid}
            }
        
        @audit_log(
            operation=AuditTrail.UPDATE,
            module='finance',
            entity_type='Invoice',
            extract_changes=extract_payment_changes
        )
        def update_invoice(invoice_id, **kwargs):
            # Update invoice
            pass
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            try:
                # Extract entity ID from args or kwargs
                entity_id = None
                user = None
                request = None
                
                # Try to find entity_id in args/kwargs
                if entity_id_field in kwargs:
                    entity_id = kwargs[entity_id_field]
                # Try to get from positional args
                elif len(args) > 0:
                    if hasattr(args[0], entity_id_field):
                        entity_id = getattr(args[0], entity_id_field)
                    elif len(args) > 1 and isinstance(args[1], (int, str)):
                        entity_id = args[1]
                
                # Try to find user and request
                if 'user' in kwargs:
                    user = kwargs['user']
                elif 'request' in kwargs:
                    request = kwargs['request']
                    user = request.user if hasattr(request, 'user') else None
                
                # Call the wrapped function
                result = func(*args, **kwargs)
                
                # Extract changes if provided
                changes = None
                if extract_changes and result:
                    changes = extract_changes(*args, **kwargs)
                
                # Log audit trail
                if entity_id:
                    AuditTrail.log(
                        operation=operation,
                        module=module,
                        entity_type=entity_type,
                        entity_id=entity_id,
                        user=user,
                        changes=changes,
                        request=request
                    )
                
                return result
                
            except Exception as e:
                logger.error(f"Error in audit_log decorator: {str(e)}", exc_info=True)
                # Don't fail the wrapped function
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


# Convenience logger for audit events
audit_logger = logging.getLogger('audit')


def log_payment_operation(
    payment_id: Any,
    amount: float,
    method: str,
    status: str,
    user: Optional[User] = None,
    reference: Optional[str] = None,
    request=None
):
    """Log a payment operation."""
    return AuditTrail.log(
        operation=AuditTrail.PAYMENT,
        module='finance',
        entity_type='Payment',
        entity_id=payment_id,
        user=user,
        changes={
            'amount': {'new': amount},
            'method': {'new': method},
            'status': {'new': status},
            'reference': {'new': reference}
        },
        reason=f"Payment of {amount} via {method}",
        request=request
    )


def log_payroll_operation(
    payslip_id: Any,
    employee_id: Any,
    operation_type: str,
    status: str,
    user: Optional[User] = None,
    request=None
):
    """Log a payroll operation."""
    return AuditTrail.log(
        operation=operation_type,
        module='hrm',
        entity_type='Payslip',
        entity_id=payslip_id,
        user=user,
        changes={
            'employee_id': {'new': employee_id},
            'status': {'new': status}
        },
        reason=f"Payroll {operation_type.lower()} for employee {employee_id}",
        request=request
    )


def log_approval_operation(
    approval_id: Any,
    entity_type: str,
    entity_id: Any,
    action: str,  # 'approve', 'reject', 'revoke'
    reason: Optional[str] = None,
    user: Optional[User] = None,
    request=None
):
    """Log an approval/rejection operation."""
    return AuditTrail.log(
        operation=AuditTrail.APPROVAL,
        module='approvals',
        entity_type=entity_type,
        entity_id=entity_id,
        user=user,
        changes={
            'action': {'new': action},
            'approval_id': {'new': approval_id}
        },
        reason=reason or f"{entity_type} {action.upper()}",
        request=request
    )


def log_asset_transfer(
    asset_id: Any,
    from_location: str,
    to_location: str,
    reason: Optional[str] = None,
    user: Optional[User] = None,
    request=None
):
    """Log an asset transfer operation."""
    return AuditTrail.log(
        operation=AuditTrail.TRANSFER,
        module='assets',
        entity_type='Asset',
        entity_id=asset_id,
        user=user,
        changes={
            'location': {'old': from_location, 'new': to_location}
        },
        reason=reason or f"Asset transferred from {from_location} to {to_location}",
        request=request
    )
