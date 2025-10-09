from datetime import datetime
from celery import shared_task
from django.core.mail.backends.smtp import EmailBackend
from django.core.mail import EmailMessage
from django.utils.html import strip_tags
from django.contrib.sites.models import Site
from notifications.models import EmailConfiguration, EmailLog
from business.models import Bussiness
import re

@shared_task
def send_email_task(subject, body, to, attachments=None):
    """
    Celery task to send emails asynchronously using centralized notifications.
    """
    from notifications.services import EmailService
    
    try:
        email_service = EmailService()
        result = email_service.send_email(
            subject=subject,
            message=body,
            recipient_list=to,
            attachments=attachments,
            async_send=False  # Already running asynchronously
        )
        
        return result
        
    except Exception as e:
        print(f"Email send error: {e}")
        return {
            "success": False,
            "error": str(e)
        }