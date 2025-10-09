"""
Centralized SMS Service
Consolidates SMS functionality from integrations app
"""
import logging
import json
from typing import List, Dict, Any, Optional, Union, Tuple
from abc import ABC, abstractmethod
from django.db import transaction
from django.utils import timezone
from celery import shared_task

from ..models import (
    NotificationIntegration, SMSConfiguration, SMSTemplate, SMSLog
)

logger = logging.getLogger('notifications')

# Try importing Twilio
try:
    from twilio.rest import Client as TwilioClient
    TWILIO_AVAILABLE = True
except ImportError:
    TWILIO_AVAILABLE = False
    logger.warning("Twilio package not installed. Install with 'pip install twilio'")

# Try importing AfricasTalking
try:
    import africastalking
    AFRICASTALKING_AVAILABLE = True
except ImportError:
    AFRICASTALKING_AVAILABLE = False
    logger.warning("AfricasTalking package not installed. Install with 'pip install africastalking'")

# Try importing boto3 for AWS SNS
try:
    import boto3
    from botocore.exceptions import ClientError
    AWS_SNS_AVAILABLE = True
except ImportError:
    AWS_SNS_AVAILABLE = False
    logger.warning("boto3 package not installed. Install with 'pip install boto3'")


class SMSProvider(ABC):
    """Abstract base class for SMS providers"""
    
    @abstractmethod
    def send_sms(self, to: str, message: str) -> Tuple[bool, str]:
        """
        Send SMS message
        
        Args:
            to: Recipient phone number
            message: SMS message content
            
        Returns:
            Tuple of (success, result/error)
        """
        pass
    
    def format_phone_number(self, phone_number: str, country_code: str = '+254') -> str:
        """
        Format phone number to international format
        
        Args:
            phone_number: Phone number to format
            country_code: Default country code to use
            
        Returns:
            Formatted phone number
        """
        # Remove any spaces or formatting characters
        phone = ''.join(filter(str.isdigit, phone_number))
        
        # Format to international format if not already
        if not phone.startswith('+'):
            if phone.startswith('0'):
                phone = country_code + phone[1:]
            else:
                phone = '+' + phone
                
        return phone


class TwilioSMSProvider(SMSProvider):
    """SMS provider implementation using Twilio"""
    
    def __init__(self, account_sid: str, auth_token: str, from_number: str):
        """
        Initialize the Twilio SMS provider
        
        Args:
            account_sid: Twilio account SID
            auth_token: Twilio auth token
            from_number: Sender phone number
        """
        if not TWILIO_AVAILABLE:
            raise ImportError("Twilio package not installed. Install with 'pip install twilio'")
            
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        
        # Initialize Twilio client
        self.client = TwilioClient(self.account_sid, self.auth_token)
        
    def send_sms(self, to: str, message: str) -> Tuple[bool, str]:
        """
        Send SMS using Twilio
        
        Args:
            to: Recipient phone number
            message: SMS message content
            
        Returns:
            Tuple of (success, result/error)
        """
        try:
            # Format phone number
            to = self.format_phone_number(to)
                    
            # Send message via Twilio
            response = self.client.messages.create(
                body=message,
                from_=self.from_number,
                to=to
            )
            
            logger.info(f"SMS sent to {to} with message ID: {response.sid}")
            return True, response.sid
            
        except Exception as e:
            logger.error(f"Failed to send Twilio SMS: {str(e)}")
            return False, str(e)


class AfricasTalkingSMSProvider(SMSProvider):
    """SMS provider implementation using Africa's Talking"""
    
    def __init__(self, username: str, api_key: str, sender: Optional[str] = None):
        """
        Initialize the Africa's Talking SMS provider
        
        Args:
            username: Africa's Talking username
            api_key: Africa's Talking API key
            sender: Optional sender ID
        """
        if not AFRICASTALKING_AVAILABLE:
            raise ImportError("AfricasTalking package not installed. Install with 'pip install africastalking'")
            
        self.username = username
        self.api_key = api_key
        self.sender = sender
        
        # Initialize AfricasTalking client
        africastalking.initialize(self.username, self.api_key)
        self.sms = africastalking.SMS
        
    def send_sms(self, to: str, message: str) -> Tuple[bool, str]:
        """
        Send SMS using Africa's Talking
        
        Args:
            to: Recipient phone number
            message: SMS message content
            
        Returns:
            Tuple of (success, result/error)
        """
        try:
            # Format phone number
            to = self.format_phone_number(to)
            
            # Prepare parameters
            params = {
                'to': [to],
                'message': message
            }
            
            # Add sender ID if provided
            if self.sender:
                params['from'] = self.sender
                
            # Send message via Africa's Talking
            response = self.sms.send(**params)
            
            # Check response status
            if response and 'SMSMessageData' in response:
                sms_data = response['SMSMessageData']
                recipients = sms_data.get('Recipients', [])
                
                if recipients and len(recipients) > 0:
                    recipient = recipients[0]
                    if recipient.get('status') == 'Success':
                        logger.info(f"SMS sent to {to} with message ID: {recipient.get('messageId')}")
                        return True, recipient.get('messageId')
                    
            logger.error(f"Failed to send AfricasTalking SMS: {json.dumps(response)}")
            return False, "SMS sending failed"
            
        except Exception as e:
            logger.error(f"Failed to send AfricasTalking SMS: {str(e)}")
            return False, str(e)


class AWSSNSProvider(SMSProvider):
    """SMS provider implementation using AWS SNS"""
    
    def __init__(self, access_key: str, secret_key: str, region: str = 'us-east-1'):
        """
        Initialize the AWS SNS provider
        
        Args:
            access_key: AWS access key
            secret_key: AWS secret key
            region: AWS region
        """
        if not AWS_SNS_AVAILABLE:
            raise ImportError("boto3 package not installed. Install with 'pip install boto3'")
            
        self.access_key = access_key
        self.secret_key = secret_key
        self.region = region
        
        # Initialize AWS SNS client
        self.client = boto3.client(
            'sns',
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region
        )
        
    def send_sms(self, to: str, message: str) -> Tuple[bool, str]:
        """
        Send SMS using AWS SNS
        
        Args:
            to: Recipient phone number
            message: SMS message content
            
        Returns:
            Tuple of (success, result/error)
        """
        try:
            # Format phone number
            to = self.format_phone_number(to)
            
            # Send message via AWS SNS
            response = self.client.publish(
                PhoneNumber=to,
                Message=message
            )
            
            message_id = response.get('MessageId')
            logger.info(f"SMS sent to {to} with message ID: {message_id}")
            return True, message_id
            
        except ClientError as e:
            logger.error(f"Failed to send AWS SNS SMS: {str(e)}")
            return False, str(e)
        except Exception as e:
            logger.error(f"Failed to send AWS SNS SMS: {str(e)}")
            return False, str(e)


class SMSService:
    """
    Centralized service for sending SMS throughout the application.
    Consolidates functionality from integrations app.
    """
    
    def __init__(self, integration: Optional[NotificationIntegration] = None, provider: Optional[str] = None):
        """
        Initialize the SMS service with optional integration configuration.
        
        Args:
            integration: Specific SMS integration to use, otherwise uses default
            provider: Optional provider override
        """
        self.integration = integration
        self.config = None
        self._provider = None
        self._provider_name = provider
        
        if integration is None and provider is None:
            try:
                # Use the default SMS integration
                self.integration = NotificationIntegration.objects.filter(
                    integration_type='SMS', 
                    is_active=True, 
                    is_default=True
                ).first()
                
                # If no default is found, use any active SMS integration
                if self.integration is None:
                    self.integration = NotificationIntegration.objects.filter(
                        integration_type='SMS', 
                        is_active=True
                    ).first()
            except Exception as e:
                logger.error(f"Error finding SMS integration: {str(e)}")
                self.integration = None
        
        if self.integration:
            try:
                self.config = SMSConfiguration.objects.get(integration=self.integration)
                if not provider:
                    self._provider_name = self.config.provider
            except SMSConfiguration.DoesNotExist:
                logger.error(f"SMS configuration not found for integration: {self.integration.name}")
    
    @property
    def provider(self) -> SMSProvider:
        """
        Get the SMS provider instance based on configuration.
        
        Returns:
            SMSProvider instance
        """
        if self._provider is not None:
            return self._provider
            
        if not self.config:
            raise ValueError("No SMS configuration available")
            
        provider_name = self._provider_name or self.config.provider
        
        if provider_name == 'TWILIO':
            if not TWILIO_AVAILABLE:
                raise ImportError("Twilio package not installed")
                
            self._provider = TwilioSMSProvider(
                account_sid=self.config.account_sid,
                auth_token=self.config.auth_token,
                from_number=self.config.from_number
            )
        
        elif provider_name == 'AFRICASTALKING':
            if not AFRICASTALKING_AVAILABLE:
                raise ImportError("AfricasTalking package not installed")
                
            self._provider = AfricasTalkingSMSProvider(
                username=self.config.api_username,
                api_key=self.config.api_key
            )
        
        elif provider_name == 'AWS_SNS':
            if not AWS_SNS_AVAILABLE:
                raise ImportError("boto3 package not installed")
                
            self._provider = AWSSNSProvider(
                access_key=self.config.aws_access_key,
                secret_key=self.config.aws_secret_key,
                region=self.config.aws_region
            )
        
        else:
            raise ValueError(f"Unsupported SMS provider: {provider_name}")
            
        return self._provider
        
    def send_sms(
        self, 
        to: Union[str, List[str]], 
        message: str, 
        async_send: bool = True, 
        sender: Optional[str] = None
    ) -> Union[str, Dict[str, Any]]:
        """
        Send SMS message
        
        Args:
            to: Recipient phone number or list of phone numbers
            message: SMS message content
            async_send: Whether to send SMS asynchronously (default True)
            sender: Optional sender override
            
        Returns:
            If async_send is True, returns the task ID.
            If async_send is False, returns a dict with status info.
        """
        # Convert list of recipients to string for DB storage
        recipient_display = to if isinstance(to, str) else ", ".join(to)
        
        # Create SMS log entry
        sms_log = SMSLog.objects.create(
            integration=self.integration,
            sender=sender or (self.config.from_number if self.config else None),
            recipient=recipient_display,
            message=message,
            status='PENDING',
            provider=self._provider_name or (self.config.provider if self.config else 'UNKNOWN')
        )
        
        if async_send:
            # Send using Celery task asynchronously
            task = send_sms_task.delay(
                to=to,
                message=message,
                sms_log_id=sms_log.id,
                integration_id=self.integration.id if self.integration else None,
                provider=self._provider_name,
                sender=sender
            )
            return task.id
        else:
            # Send synchronously
            try:
                return self._send_sms_internal(
                    to=to,
                    message=message,
                    sms_log_id=sms_log.id,
                    sender=sender
                )
            except Exception as e:
                logger.error(f"Error sending SMS: {str(e)}")
                sms_log.status = 'FAILED'
                sms_log.error_message = str(e)
                sms_log.save()
                return {
                    'success': False,
                    'error': str(e),
                    'sms_log_id': sms_log.id
                }
    
    def _send_sms_internal(
        self, 
        to: Union[str, List[str]], 
        message: str, 
        sms_log_id: Optional[int] = None, 
        sender: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Internal method to send SMS (used both by sync and async sending).
        
        Args:
            to: Recipient phone number or list of phone numbers
            message: SMS message content
            sms_log_id: Optional SMS log ID for updating status
            sender: Optional sender override
            
        Returns:
            Dict with success status and message ID
        """
        try:
            # Get provider
            sms_provider = self.provider
            
            # Format recipient if it's a list
            recipient = to[0] if isinstance(to, list) and len(to) > 0 else to
            
            # Send the SMS
            success, result = sms_provider.send_sms(recipient, message)
            
            # Update log status
            if sms_log_id:
                with transaction.atomic():
                    sms_log = SMSLog.objects.get(id=sms_log_id)
                    sms_log.status = 'SENT' if success else 'FAILED'
                    if not success:
                        sms_log.error_message = result
                    else:
                        sms_log.message_id = result
                        sms_log.delivered_at = timezone.now()
                    sms_log.save()
            
            return {
                'success': success,
                'result': result,
                'sms_log_id': sms_log_id
            }
            
        except Exception as e:
            # Update log status on failure
            if sms_log_id:
                with transaction.atomic():
                    sms_log = SMSLog.objects.get(id=sms_log_id)
                    sms_log.status = 'FAILED'
                    sms_log.error_message = str(e)
                    sms_log.save()
            
            logger.error(f"Failed to send SMS: {str(e)}")
            raise
    
    def send_template_sms(
        self, 
        template_name: str, 
        context: Dict[str, Any], 
        to: Union[str, List[str]], 
        async_send: bool = True, 
        sender: Optional[str] = None
    ) -> Union[str, Dict[str, Any]]:
        """
        Send SMS using a template from the database.
        
        Args:
            template_name: Name of the SMS template to use
            context: Dictionary of context variables for rendering the template
            to: Recipient phone number or list of phone numbers
            async_send: Whether to send SMS asynchronously (default True)
            sender: Optional sender override
            
        Returns:
            If async_send is True, returns the task ID.
            If async_send is False, returns a dict with status info.
        """
        try:
            # Get the template
            template = SMSTemplate.objects.get(name=template_name, is_active=True)
            
            # Render message with context
            message = template.content
            for key, value in context.items():
                message = message.replace(f"{{{key}}}", str(value))
                
            # Send the SMS
            return self.send_sms(
                to=to,
                message=message,
                async_send=async_send,
                sender=sender
            )
        
        except SMSTemplate.DoesNotExist:
            logger.error(f"SMS template '{template_name}' not found")
            return {
                'success': False,
                'error': f"SMS template '{template_name}' not found"
            }
        except Exception as e:
            logger.error(f"Error sending template SMS: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_bulk_sms(
        self, 
        sms_data_list: List[Dict[str, Any]], 
        async_send: bool = True
    ) -> Dict[str, Any]:
        """
        Send multiple SMS messages efficiently.
        
        Args:
            sms_data_list: List of dictionaries with SMS parameters
            async_send: Whether to send SMS asynchronously
            
        Returns:
            Dictionary with summary of SMS sending results
        """
        results = []
        success_count = 0
        failure_count = 0
        
        for sms_data in sms_data_list:
            try:
                to = sms_data.get('to')
                message = sms_data.get('message')
                sender = sms_data.get('sender')
                
                result = self.send_sms(
                    to=to,
                    message=message,
                    async_send=async_send,
                    sender=sender
                )
                
                if async_send:
                    results.append({
                        'task_id': result,
                        'status': 'queued',
                        'recipient': to
                    })
                    success_count += 1
                else:
                    if result.get('success', False):
                        results.append({
                            'status': 'sent',
                            'recipient': to,
                            'message_id': result.get('result'),
                            'sms_log_id': result.get('sms_log_id')
                        })
                        success_count += 1
                    else:
                        results.append({
                            'status': 'failed',
                            'error': result.get('error'),
                            'recipient': to,
                            'sms_log_id': result.get('sms_log_id')
                        })
                        failure_count += 1
                        
            except Exception as e:
                results.append({
                    'status': 'failed',
                    'error': str(e),
                    'recipient': sms_data.get('to')
                })
                failure_count += 1
        
        return {
            'total': len(sms_data_list),
            'success': success_count,
            'failed': failure_count,
            'results': results
        }
    
    def get_available_templates(self, category: Optional[str] = None) -> List[SMSTemplate]:
        """
        Get available SMS templates.
        
        Args:
            category: Optional category filter
            
        Returns:
            List of SMSTemplate objects
        """
        queryset = SMSTemplate.objects.filter(is_active=True)
        if category:
            queryset = queryset.filter(category=category)
        return queryset.order_by('category', 'name')
    
    def create_template(
        self, 
        name: str, 
        content: str, 
        category: str = "general",
        description: Optional[str] = None,
        available_variables: Optional[str] = None
    ) -> SMSTemplate:
        """
        Create a new SMS template.
        
        Args:
            name: Template name
            content: SMS content with {variable} placeholders
            category: Template category
            description: Template description
            available_variables: Documentation of available variables
            
        Returns:
            Created SMSTemplate object
        """
        return SMSTemplate.objects.create(
            name=name,
            content=content,
            category=category,
            description=description,
            available_variables=available_variables
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_sms_task(
    self, 
    to: Union[str, List[str]], 
    message: str, 
    sms_log_id: Optional[int] = None, 
    integration_id: Optional[int] = None, 
    provider: Optional[str] = None, 
    sender: Optional[str] = None
) -> Dict[str, Any]:
    """
    Celery task for sending SMS asynchronously.
    """
    try:
        # Initialize SMS service with the specified integration if provided
        if integration_id:
            try:
                integration = NotificationIntegration.objects.get(id=integration_id)
                sms_service = SMSService(integration=integration, provider=provider)
            except NotificationIntegration.DoesNotExist:
                sms_service = SMSService(provider=provider)
        else:
            sms_service = SMSService(provider=provider)
        
        # Send the SMS
        return sms_service._send_sms_internal(
            to=to,
            message=message,
            sms_log_id=sms_log_id,
            sender=sender
        )
    
    except Exception as e:
        logger.error(f"Error in send_sms_task: {str(e)}")
        
        # Update log status
        if sms_log_id:
            try:
                with transaction.atomic():
                    sms_log = SMSLog.objects.get(id=sms_log_id)
                    sms_log.status = 'FAILED'
                    sms_log.error_message = f"Attempt {self.request.retries + 1}: {str(e)}"
                    sms_log.save()
            except Exception as log_error:
                logger.error(f"Failed to update SMS log: {str(log_error)}")
        
        # Retry the task if we haven't exceeded retry limits
        try:
            raise self.retry(exc=e)
        except Exception as retry_error:
            return {
                'success': False,
                'error': f"Failed after retries: {str(e)}",
                'sms_log_id': sms_log_id
            }
