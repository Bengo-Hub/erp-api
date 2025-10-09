"""
Integration utilities for easy access from other apps.
This module provides simple functions that can be imported directly by other apps 
to use the integration services without dealing with the full service objects.
"""

from .services import get_email_service, get_sms_service, get_notification_service
from finance.payment.models import BillingDocument


# Email utilities
def send_email(subject, message, recipient_list, html_message=None, **kwargs):
    """
    Send an email using the default email integration.
    
    Args:
        subject: Email subject
        message: Plain text message
        recipient_list: List of email recipients
        html_message: Optional HTML version of the message
        **kwargs: Additional email parameters
        
    Returns:
        Task ID or result dictionary
    """
    email_service = get_email_service()
    return email_service.send_email(
        subject=subject, 
        message=message,
        recipient_list=recipient_list,
        html_message=html_message,
        **kwargs
    )

def send_template_email(template_name, context, recipient_list, **kwargs):
    """
    Send an email using a template from the database.
    
    Args:
        template_name: Name of the template in the database
        context: Dictionary of context variables for rendering
        recipient_list: List of email recipients
        **kwargs: Additional email parameters
        
    Returns:
        Task ID or result dictionary
    """
    email_service = get_email_service()
    return email_service.send_template_email(
        template_name=template_name,
        context=context,
        recipient_list=recipient_list,
        **kwargs
    )

def send_django_template_email(template_name, context, subject, recipient_list, **kwargs):
    """
    Send an email using a Django template file.
    
    Args:
        template_name: Path to the Django template
        context: Dictionary of context variables for rendering
        subject: Email subject
        recipient_list: List of email recipients
        **kwargs: Additional email parameters
        
    Returns:
        Task ID or result dictionary
    """
    email_service = get_email_service()
    return email_service.send_django_template_email(
        template_name=template_name,
        context=context,
        subject=subject,
        recipient_list=recipient_list,
        **kwargs
    )

# SMS utilities
def send_sms(to, message, **kwargs):
    """
    Send an SMS using the default SMS integration.
    
    Args:
        to: Recipient phone number
        message: SMS content
        **kwargs: Additional SMS parameters
        
    Returns:
        Task ID or result dictionary
    """
    sms_service = get_sms_service()
    return sms_service.send_sms(
        to=to,
        message=message,
        **kwargs
    )

def send_template_sms(template_name, context, to, **kwargs):
    """
    Send an SMS using a template from the database.
    
    Args:
        template_name: Name of the template in the database
        context: Dictionary of context variables for rendering
        to: Recipient phone number
        **kwargs: Additional SMS parameters
        
    Returns:
        Task ID or result dictionary
    """
    sms_service = get_sms_service()
    return sms_service.send_template_sms(
        template_name=template_name,
        context=context,
        to=to,
        **kwargs
    )

# Notification utilities
def send_notification(user, title, message, notification_type, **kwargs):
    """
    Send a notification to a user through configured channels.
    
    Args:
        user: User object or user ID to notify
        title: Notification title
        message: Notification message
        notification_type: Type of notification (e.g., 'order', 'payment')
        **kwargs: Additional notification parameters
        
    Returns:
        Dictionary with notification results
    """
    notification_service = get_notification_service()
    return notification_service.send_notification(
        user=user,
        title=title,
        message=message,
        notification_type=notification_type,
        **kwargs
    )

def send_many_notifications(users, title, message, notification_type, **kwargs):
    """
    Send notifications to multiple users.
    
    Args:
        users: List of users or user IDs
        title: Notification title
        message: Notification message
        notification_type: Type of notification
        **kwargs: Additional notification parameters
        
    Returns:
        Dictionary with notification results
    """
    notification_service = get_notification_service()
    return notification_service.send_notification_to_many(
        users=users,
        title=title,
        message=message,
        notification_type=notification_type,
        **kwargs
    )

# Order-specific notification utilities
def send_order_notification(order, event_type, **kwargs):
    """
    Send an order-related notification.
    
    Args:
        order: Order object to send notification for
        event_type: Event type (confirmed, processing, shipped, etc.)
        **kwargs: Additional notification parameters
        
    Returns:
        Dictionary with notification results
    """
    # Dictionary of notification templates by event type
    templates = {
        'order_confirmed': {
            'title': 'Order Confirmed',
            'message': f"Thank you for your order #{order.order_id}. Your order has been confirmed and will be processed shortly.",
        },
        'order_processing': {
            'title': 'Order Processing',
            'message': f"Your order #{order.order_id} is now being processed.",
        },
        'order_shipped': {
            'title': 'Order Shipped',
            'message': f"Good news! Your order #{order.order_id} has been shipped. You can track your delivery with tracking number: {getattr(order, 'tracking_number', 'N/A')}.",
        },
        'order_delivered': {
            'title': 'Order Delivered',
            'message': f"Your order #{order.order_id} has been delivered. Thank you for shopping with us!",
        },
        'order_cancelled': {
            'title': 'Order Cancelled',
            'message': f"Your order #{order.order_id} has been cancelled. Please contact customer service for more information.",
        },
        'order_refunded': {
            'title': 'Order Refunded',
            'message': f"Your refund for order #{order.order_id} has been processed. It may take a few days to appear in your account.",
        },
        'payment_received': {
            'title': 'Payment Received',
            'message': f"We've received your payment of {getattr(order, 'amount_paid', 'your payment')} for order #{order.order_id}. Thank you!",
        },
        'payment_failed': {
            'title': 'Payment Failed',
            'message': f"There was an issue processing your payment for order #{order.order_id}. Please update your payment information.",
        },
    }
    
    # Get the template for this event type
    template = templates.get(event_type)
    if not template:
        return {
            'success': False,
            'error': f"Unknown event type: {event_type}"
        }
    
    # Get user from order if available
    user = getattr(order, 'user', None)
    if not user:
        return {
            'success': False,
            'error': "Order has no associated user"
        }
    
    # Prepare notification data
    notification_data = {
        'order_id': getattr(order, 'order_id', str(order.id)),
        'order_status': event_type,
        'order_amount': getattr(order, 'amount_paid', None),
        'order_date': getattr(order, 'created_at', None),
    }
    
    # Send notification with order details
    notification_service = get_notification_service()
    return notification_service.send_notification(
        user=user,
        title=template['title'],
        message=template['message'],
        notification_type='order',
        data=notification_data,
        **kwargs
    )

# Payment notification utilities
def send_payment_notification(payment, event_type, **kwargs):
    """
    Send a payment-related notification.
    
    Args:
        payment: Payment object to send notification for
        event_type: Event type (successful, failed, refunded, etc.)
        **kwargs: Additional notification parameters
        
    Returns:
        Dictionary with notification results
    """
    # Dictionary of notification templates by event type
    templates = {
        'payment_successful': {
            'title': 'Payment Successful',
            'message': f"Your payment of {getattr(payment, 'amount', '')} has been successfully processed.",
        },
        'payment_failed': {
            'title': 'Payment Failed',
            'message': f"Your payment of {getattr(payment, 'amount', '')} has failed. Please try again or contact support.",
        },
        'payment_refunded': {
            'title': 'Payment Refunded',
            'message': f"Your payment of {getattr(payment, 'amount', '')} has been refunded. It may take a few days to appear in your account.",
        },
        'payment_pending': {
            'title': 'Payment Pending',
            'message': f"Your payment of {getattr(payment, 'amount', '')} is pending confirmation.",
        },
    }
    
    # Get the template for this event type
    template = templates.get(event_type)
    if not template:
        return {
            'success': False,
            'error': f"Unknown event type: {event_type}"
        }
    
    # Get user from payment if available
    user = getattr(payment, 'user', None)
    if not user:
        return {
            'success': False,
            'error': "Payment has no associated user"
        }
    
    # Prepare notification data
    payment_method = getattr(payment, 'payment_method', 'Unknown')
    reference = getattr(payment, 'reference', getattr(payment, 'id', 'Unknown'))
    
    notification_data = {
        'payment_id': getattr(payment, 'id', None),
        'payment_amount': getattr(payment, 'amount', None),
        'payment_method': payment_method,
        'payment_reference': reference,
        'payment_date': getattr(payment, 'created_at', None),
    }
    
    # Send notification with payment details
    notification_service = get_notification_service()
    return notification_service.send_notification(
        user=user,
        title=template['title'],
        message=template['message'],
        notification_type='payment',
        data=notification_data,
        **kwargs
    )


# -----------------------------
# KRA eTIMS payload utilities
# -----------------------------
def build_kra_invoice_payload_from_billing_document(document: BillingDocument) -> dict:
    """
    Build a minimal eTIMS invoice payload from a BillingDocument.
    This is a best-effort mapping and may need adjustment to match KRA schema.
    """
    customer_name = getattr(document.customer, 'name', '') if document.customer else ''
    customer_pin = getattr(document.customer, 'kra_pin', '') if document.customer else ''
    items = []
    for item in document.billing_items.all():
        items.append({
            'description': item.description,
            'quantity': float(item.quantity),
            'unit_price': float(item.unit_price),
            'tax_rate': float(item.tax_rate),
            'total': float(item.total),
        })

    payload = {
        'invoice_number': document.document_number,
        'issue_date': str(document.issue_date),
        'customer': {
            'name': customer_name,
            'kra_pin': customer_pin,
        },
        'totals': {
            'subtotal': float(document.subtotal),
            'tax_amount': float(document.tax_amount),
            'total': float(document.total),
        },
        'items': items,
    }
    return payload
