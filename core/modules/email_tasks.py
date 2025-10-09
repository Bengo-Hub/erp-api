"""
Email queue processing tasks.
This module contains optimized tasks for handling email operations asynchronously.
Now using centralized notifications app.
"""
from celery import shared_task
import logging
from django.core.cache import cache
from notifications.services import EmailService
from datetime import datetime

logger = logging.getLogger('ditapi_logger')

@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_email_with_retry(self, subject, body, recipients, attachments=None, cc=None, bcc=None, reply_to=None):
    """
    Send an email with retry capability.
    
    Args:
        subject: Email subject
        body: Email body content
        recipients: List of recipient email addresses
        attachments: Optional list of attachments
        cc: Optional list of CC recipients
        bcc: Optional list of BCC recipients
        reply_to: Optional reply-to email address
    
    Returns:
        Dictionary with email sending result
    """
    try:
        logger.info(f"Sending email to {recipients} with subject: {subject}")
        
        # Use centralized email service
        email_service = EmailService()
        result = email_service.send_email(
            subject=subject,
            message=body,
            recipient_list=recipients,
            attachments=attachments,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            async_send=False  # Already running asynchronously
        )
        
        # Log the result
        if result.get('success', False):
            logger.info(f"Email sent successfully to {recipients}")
        else:
            logger.warning(f"Email sending failed: {result.get('error')}")
        
        return result
    
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}")
        
        # Retry the task if we haven't exceeded the retry limit
        try:
            raise self.retry(exc=e)
        except Exception as retry_error:
            return {
                "success": False,
                "error": f"Failed after retries: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }

@shared_task
def send_bulk_emails(email_data_list):
    """
    Send multiple emails asynchronously using centralized notifications.
    
    Args:
        email_data_list: List of dictionaries, each containing:
            - subject
            - body
            - recipients (list)
            - attachments (optional)
            - cc (optional)
            - bcc (optional)
            - reply_to (optional)
    
    Returns:
        Dictionary with results from all email sends
    """
    from notifications.services import EmailService
    
    email_service = EmailService()
    result = email_service.send_bulk_email(
        email_data_list=email_data_list,
        async_send=True
    )
    
    return result

@shared_task
def send_template_email(template_key, context, recipients, attachments=None, cc=None, bcc=None, reply_to=None):
    """
    Send an email using a predefined template from centralized notifications.
    
    Args:
        template_key: Key to identify the email template
        context: Dictionary of context variables for the template
        recipients: List of recipient email addresses
        attachments: Optional list of attachments
        cc: Optional list of CC recipients
        bcc: Optional list of BCC recipients
        reply_to: Optional reply-to email address
    
    Returns:
        Dictionary with email sending result
    """
    try:
        from notifications.services import EmailService
        
        email_service = EmailService()
        result = email_service.send_template_email(
            template_name=template_key,
            context=context,
            recipient_list=recipients,
            attachments=attachments,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            async_send=False  # Already running asynchronously
        )
        
        return result
    
    except Exception as e:
        logger.error(f"Error sending template email: {str(e)}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }
