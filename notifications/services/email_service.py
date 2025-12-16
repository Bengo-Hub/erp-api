"""
Centralized Email Service
Consolidates email functionality from core and integrations apps
"""
import logging
import re
import base64
from typing import List, Dict, Any, Optional, Union
from django.core.mail import EmailMessage, EmailMultiAlternatives
from django.core.mail.backends.smtp import EmailBackend
from django.template.loader import render_to_string
from django.utils.html import strip_tags
from django.db import transaction
from django.utils import timezone
from celery import shared_task

from ..models import (
    NotificationIntegration, EmailConfiguration, EmailTemplate, EmailLog
)

logger = logging.getLogger('notifications')


def _encode_attachments_for_celery(attachments: Optional[List]) -> Optional[List]:
    """
    Encode binary attachment content to base64 for Celery serialization.
    
    Celery uses JSON serialization by default and cannot handle binary data.
    This function converts attachment tuples to a format that can survive
    the serialization/deserialization process.
    
    Args:
        attachments: List of attachment tuples (filename, content, mimetype)
        
    Returns:
        List of encoded attachment tuples with binary content as base64 strings
    """
    if not attachments:
        return None
    
    encoded = []
    for attachment in attachments:
        if isinstance(attachment, tuple) and len(attachment) >= 3:
            filename, content, mimetype = attachment[0], attachment[1], attachment[2]
            
            # If content is bytes, encode to base64
            if isinstance(content, bytes):
                try:
                    encoded_content = base64.b64encode(content).decode('utf-8')
                    # Mark as base64 by prepending marker
                    encoded.append((filename, f"__b64__{encoded_content}", mimetype))
                except Exception as e:
                    logger.warning(f"Failed to encode attachment {filename}: {str(e)}")
                    # Fall back to original (may fail in Celery, but worth trying)
                    encoded.append(attachment)
            else:
                # String or other type, pass through
                encoded.append(attachment)
        else:
            encoded.append(attachment)
    
    return encoded if encoded else None


def _decode_attachments_from_celery(attachments: Optional[List]) -> Optional[List]:
    """
    Decode base64 attachment content that was encoded for Celery serialization.
    
    Args:
        attachments: List of attachment tuples with base64-encoded content
        
    Returns:
        List of attachment tuples with binary content decoded from base64
    """
    if not attachments:
        return None
    
    decoded = []
    for attachment in attachments:
        if isinstance(attachment, tuple) and len(attachment) >= 3:
            filename, content, mimetype = attachment[0], attachment[1], attachment[2]
            
            # If content has base64 marker, decode it
            if isinstance(content, str) and content.startswith("__b64__"):
                try:
                    encoded_content = content[7:]  # Remove marker
                    decoded_content = base64.b64decode(encoded_content)
                    decoded.append((filename, decoded_content, mimetype))
                except Exception as e:
                    logger.warning(f"Failed to decode attachment {filename}: {str(e)}")
                    # Fall back to original
                    decoded.append(attachment)
            else:
                # Not base64 encoded, pass through
                decoded.append(attachment)
        else:
            decoded.append(attachment)
    
    return decoded if decoded else None


class EmailService:
    """
    Centralized service for sending emails throughout the application.
    Consolidates functionality from core and integrations apps.
    """
    
    def __init__(self, integration: Optional[NotificationIntegration] = None):
        """
        Initialize the email service with optional integration configuration.
        
        Args:
            integration: Specific email integration to use, otherwise uses default
        """
        self.integration = integration
        self.config = None
        
        if integration is None:
            try:
                # Use the default email integration
                self.integration = NotificationIntegration.objects.filter(
                    integration_type='EMAIL', 
                    is_active=True, 
                    is_default=True
                ).first()
                
                # If no default is found, use any active email integration
                if self.integration is None:
                    self.integration = NotificationIntegration.objects.filter(
                        integration_type='EMAIL', 
                        is_active=True
                    ).first()
            except Exception as e:
                logger.error(f"Error finding email integration: {str(e)}")
                self.integration = None
        
        if self.integration:
            try:
                self.config = EmailConfiguration.objects.get(integration=self.integration)
            except EmailConfiguration.DoesNotExist:
                logger.error(f"Email configuration not found for integration: {self.integration.name}")
    
    def get_connection(self) -> Optional[EmailBackend]:
        """
        Get the email backend connection using the integration configuration.
        Ensures encrypted passwords are decrypted before use.
        """
        if not self.config:
            logger.warning("No email configuration available, using default settings")
            return None
        
        # Get decrypted password
        decrypted_password = self.config.get_decrypted_smtp_password()
        if not decrypted_password:
            logger.warning("SMTP password not available or failed to decrypt")
            
        return EmailBackend(
            host=self.config.smtp_host,
            port=self.config.smtp_port,
            username=self.config.smtp_username,
            password=decrypted_password,  # Use decrypted password
            use_tls=self.config.use_tls,
            use_ssl=self.config.use_ssl,
            fail_silently=self.config.fail_silently,
            timeout=self.config.timeout
        )
    
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
        async_send: bool = True
    ) -> Union[str, Dict[str, Any]]:
        """
        Send an email with the specified parameters.
        
        Args:
            subject: Email subject
            message: Plain text message body
            recipient_list: List of recipient email addresses or single email
            html_message: Optional HTML message body
            from_email: Optional sender email (overrides config default)
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            reply_to: Optional reply-to address
            attachments: Optional list of attachments
            async_send: Whether to send the email asynchronously (default True)
            
        Returns:
            If async_send is True, returns the task ID.
            If async_send is False, returns a dict with status info.
        """
        # Use configuration from_email if none provided
        if not from_email and self.config:
            from_email = f"{self.config.from_name} <{self.config.from_email}>"
        
        # Convert single recipient to list
        if isinstance(recipient_list, str):
            recipient_list = [recipient_list]
            
        # Log the email
        email_log = EmailLog.objects.create(
            integration=self.integration,
            sender=from_email if from_email else (self.config.from_email if self.config else "unknown"),
            recipients=", ".join(recipient_list),
            cc=", ".join(cc) if cc else None,
            bcc=", ".join(bcc) if bcc else None,
            subject=subject,
            body=html_message if html_message else message,
            status='PENDING'
        )
        
        if async_send:
            # Encode attachments for Celery serialization (JSON-safe)
            encoded_attachments = _encode_attachments_for_celery(attachments)
            
            # Send using Celery task asynchronously
            task = send_email_task.delay(
                subject=subject,
                message=message,
                recipient_list=recipient_list,
                html_message=html_message,
                from_email=from_email,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
                attachments=encoded_attachments,
                email_log_id=email_log.id,
                integration_id=self.integration.id if self.integration else None
            )
            return task.id
        else:
            # Send synchronously
            try:
                return self._send_email_internal(
                    subject=subject,
                    message=message,
                    recipient_list=recipient_list,
                    html_message=html_message,
                    from_email=from_email,
                    cc=cc,
                    bcc=bcc,
                    reply_to=reply_to,
                    attachments=attachments,
                    email_log_id=email_log.id
                )
            except Exception as e:
                logger.error(f"Error sending email: {str(e)}")
                email_log.status = 'FAILED'
                email_log.error_message = str(e)
                email_log.save()
                return {
                    'success': False,
                    'error': str(e),
                    'email_log_id': email_log.id
                }
    
    def _send_email_internal(
        self, 
        subject: str, 
        message: str, 
        recipient_list: List[str], 
        html_message: Optional[str] = None,
        from_email: Optional[str] = None, 
        cc: Optional[List[str]] = None, 
        bcc: Optional[List[str]] = None,
        reply_to: Optional[str] = None,
        attachments: Optional[List] = None,
        email_log_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Internal method to send an email (used both by sync and async sending).
        """
        connection = self.get_connection()
        
        try:
            # Create the email message
            if html_message:
                email = EmailMultiAlternatives(
                    subject=subject,
                    body=message,
                    from_email=from_email,
                    to=recipient_list,
                    cc=cc,
                    bcc=bcc,
                    reply_to=reply_to,
                    connection=connection
                )
                email.attach_alternative(html_message, "text/html")
            else:
                email = EmailMessage(
                    subject=subject,
                    body=message,
                    from_email=from_email,
                    to=recipient_list,
                    cc=cc,
                    bcc=bcc,
                    reply_to=reply_to,
                    connection=connection
                )
            
            # Attach files if any
            if attachments:
                for attachment in attachments:
                    if hasattr(attachment, 'read'):  # File-like object
                        email.attach(
                            attachment.name, 
                            attachment.read(), 
                            getattr(attachment, 'content_type', None)
                        )
                    elif isinstance(attachment, tuple) and len(attachment) >= 3:
                        # Tuple of (filename, content, mimetype)
                        email.attach(*attachment)
            
            # Send the email
            email.send()
            
            # Update log status
            if email_log_id:
                with transaction.atomic():
                    email_log = EmailLog.objects.get(id=email_log_id)
                    email_log.status = 'SENT'
                    email_log.delivered_at = timezone.now()
                    email_log.save()
            
            return {
                'success': True,
                'email_log_id': email_log_id
            }
            
        except Exception as e:
            # Update log status on failure
            if email_log_id:
                with transaction.atomic():
                    email_log = EmailLog.objects.get(id=email_log_id)
                    email_log.status = 'FAILED'
                    email_log.error_message = str(e)
                    email_log.save()
            
            logger.error(f"Failed to send email: {str(e)}")
            raise
    
    def send_template_email(
        self, 
        template_name: str, 
        context: Dict[str, Any], 
        recipient_list: Union[List[str], str],
        attachments: Optional[List] = None, 
        cc: Optional[List[str]] = None, 
        bcc: Optional[List[str]] = None,
        reply_to: Optional[str] = None, 
        async_send: bool = True
    ) -> Union[str, Dict[str, Any]]:
        """
        Send an email using a template from the database.
        
        Args:
            template_name: Name of the email template to use
            context: Dictionary of context variables for rendering the template
            recipient_list: List of recipient email addresses or single email
            attachments: Optional list of attachments
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            reply_to: Optional reply-to address
            async_send: Whether to send the email asynchronously (default True)
            
        Returns:
            If async_send is True, returns the task ID.
            If async_send is False, returns a dict with status info.
        """
        try:
            # Get the template
            template = EmailTemplate.objects.get(name=template_name, is_active=True)
            
            # Render subject with context
            subject = template.subject
            for key, value in context.items():
                subject = subject.replace(f"{{{key}}}", str(value))
                
            # Render HTML body 
            html_message = template.body_html
            for key, value in context.items():
                html_message = html_message.replace(f"{{{key}}}", str(value))
            
            # Use plain text body if provided, otherwise strip HTML tags
            if template.body_text:
                text_message = template.body_text
                for key, value in context.items():
                    text_message = text_message.replace(f"{{{key}}}", str(value))
            else:
                text_message = strip_tags(html_message)
                
            # Send the email
            return self.send_email(
                subject=subject,
                message=text_message,
                recipient_list=recipient_list,
                html_message=html_message,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
                attachments=attachments,
                async_send=async_send
            )
        
        except EmailTemplate.DoesNotExist:
            logger.error(f"Email template '{template_name}' not found")
            return {
                'success': False,
                'error': f"Email template '{template_name}' not found"
            }
        except Exception as e:
            logger.error(f"Error sending template email: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_django_template_email(
        self, 
        template_name: str, 
        context: Dict[str, Any], 
        subject: str, 
        recipient_list: Union[List[str], str],
        attachments: Optional[List] = None, 
        cc: Optional[List[str]] = None, 
        bcc: Optional[List[str]] = None,
        reply_to: Optional[str] = None, 
        async_send: bool = True
    ) -> Union[str, Dict[str, Any]]:
        """
        Send an email using a Django template file.
        
        Args:
            template_name: Path to the Django template
            context: Dictionary of context variables for rendering the template
            subject: Email subject
            recipient_list: List of recipient email addresses or single email
            attachments: Optional list of attachments
            cc: Optional CC recipients
            bcc: Optional BCC recipients
            reply_to: Optional reply-to address
            async_send: Whether to send the email asynchronously (default True)
            
        Returns:
            If async_send is True, returns the task ID.
            If async_send is False, returns a dict with status info.
        """
        try:
            # Render HTML message from template
            html_message = render_to_string(template_name, context)
            
            # Create plain text version
            text_message = strip_tags(html_message)
            
            # Send the email
            return self.send_email(
                subject=subject,
                message=text_message,
                recipient_list=recipient_list,
                html_message=html_message,
                cc=cc,
                bcc=bcc,
                reply_to=reply_to,
                attachments=attachments,
                async_send=async_send
            )
            
        except Exception as e:
            logger.error(f"Error sending Django template email: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_bulk_emails(
        self, 
        emails_data: List[Dict[str, Any]], 
        batch_size: int = 50, 
        async_send: bool = True
    ) -> Dict[str, Any]:
        """
        Send multiple emails efficiently.
        
        Args:
            emails_data: List of dictionaries with email parameters
            batch_size: Number of emails to process in a batch
            async_send: Whether to send emails asynchronously
            
        Returns:
            Dictionary with summary of email sending results
        """
        results = []
        success_count = 0
        failure_count = 0
        
        if async_send:
            # For async, queue all tasks
            for email_data in emails_data:
                try:
                    task_id = self.send_email(
                        subject=email_data.get('subject', ''),
                        message=email_data.get('message', ''),
                        recipient_list=email_data.get('recipient_list', []),
                        html_message=email_data.get('html_message'),
                        from_email=email_data.get('from_email'),
                        cc=email_data.get('cc'),
                        bcc=email_data.get('bcc'),
                        reply_to=email_data.get('reply_to'),
                        attachments=email_data.get('attachments'),
                        async_send=True
                    )
                    
                    results.append({
                        'task_id': task_id,
                        'status': 'queued',
                        'recipient': email_data.get('recipient_list')
                    })
                    success_count += 1
                    
                except Exception as e:
                    results.append({
                        'status': 'failed',
                        'error': str(e),
                        'recipient': email_data.get('recipient_list')
                    })
                    failure_count += 1
        else:
            # For sync, process in batches with connection reuse
            connection = self.get_connection()
            
            for i in range(0, len(emails_data), batch_size):
                batch = emails_data[i:i+batch_size]
                
                for email_data in batch:
                    try:
                        result = self.send_email(
                            subject=email_data.get('subject', ''),
                            message=email_data.get('message', ''),
                            recipient_list=email_data.get('recipient_list', []),
                            html_message=email_data.get('html_message'),
                            from_email=email_data.get('from_email'),
                            cc=email_data.get('cc'),
                            bcc=email_data.get('bcc'),
                            reply_to=email_data.get('reply_to'),
                            attachments=email_data.get('attachments'),
                            async_send=False
                        )
                        
                        results.append({
                            'status': 'sent' if result.get('success', False) else 'failed',
                            'error': result.get('error'),
                            'recipient': email_data.get('recipient_list'),
                            'email_log_id': result.get('email_log_id')
                        })
                        
                        if result.get('success', False):
                            success_count += 1
                        else:
                            failure_count += 1
                            
                    except Exception as e:
                        results.append({
                            'status': 'failed',
                            'error': str(e),
                            'recipient': email_data.get('recipient_list')
                        })
                        failure_count += 1
        
        return {
            'total': len(emails_data),
            'success': success_count,
            'failed': failure_count,
            'results': results
        }
    
    def get_available_templates(self, category: Optional[str] = None) -> List[EmailTemplate]:
        """
        Get available email templates.
        
        Args:
            category: Optional category filter
            
        Returns:
            List of EmailTemplate objects
        """
        queryset = EmailTemplate.objects.filter(is_active=True)
        if category:
            queryset = queryset.filter(category=category)
        return queryset.order_by('category', 'name')
    
    def create_template(
        self, 
        name: str, 
        subject: str, 
        body_html: str, 
        body_text: Optional[str] = None,
        category: str = "general",
        description: Optional[str] = None,
        available_variables: Optional[str] = None
    ) -> EmailTemplate:
        """
        Create a new email template.
        
        Args:
            name: Template name
            subject: Email subject
            body_html: HTML body content
            body_text: Plain text body content (optional)
            category: Template category
            description: Template description
            available_variables: Documentation of available variables
            
        Returns:
            Created EmailTemplate object
        """
        return EmailTemplate.objects.create(
            name=name,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            category=category,
            description=description,
            available_variables=available_variables
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_email_task(
    self, 
    subject: str, 
    message: str, 
    recipient_list: List[str], 
    html_message: Optional[str] = None,
    from_email: Optional[str] = None, 
    cc: Optional[List[str]] = None, 
    bcc: Optional[List[str]] = None,
    reply_to: Optional[str] = None,
    attachments: Optional[List] = None,
    email_log_id: Optional[int] = None, 
    integration_id: Optional[int] = None
) -> Dict[str, Any]:
    """
    Celery task for sending emails asynchronously.
    """
    try:
        # Initialize email service with the specified integration if provided
        if integration_id:
            try:
                integration = NotificationIntegration.objects.get(id=integration_id)
                email_service = EmailService(integration=integration)
            except NotificationIntegration.DoesNotExist:
                email_service = EmailService()
        else:
            email_service = EmailService()
        
        # Decode attachments that were encoded for Celery serialization
        decoded_attachments = _decode_attachments_from_celery(attachments)
        
        # Send the email
        return email_service._send_email_internal(
            subject=subject,
            message=message,
            recipient_list=recipient_list,
            html_message=html_message,
            from_email=from_email,
            cc=cc,
            bcc=bcc,
            reply_to=reply_to,
            attachments=decoded_attachments,
            email_log_id=email_log_id
        )
    
    except Exception as e:
        logger.error(f"Error in send_email_task: {str(e)}")
        
        # Update log status
        if email_log_id:
            try:
                with transaction.atomic():
                    email_log = EmailLog.objects.get(id=email_log_id)
                    email_log.status = 'FAILED'
                    email_log.error_message = f"Attempt {self.request.retries + 1}: {str(e)}"
                    email_log.save()
            except Exception as log_error:
                logger.error(f"Failed to update email log: {str(log_error)}")
        
        # Retry the task if we haven't exceeded retry limits
        try:
            raise self.retry(exc=e)
        except Exception as retry_error:
            return {
                'success': False,
                'error': f"Failed after retries: {str(e)}",
                'email_log_id': email_log_id
            }
