"""
Centralized Push Notification Service
Consolidates push notification functionality from integrations app
"""
import logging
import json
from typing import List, Dict, Any, Optional, Union
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from celery import shared_task

from ..models import (
    NotificationIntegration, PushConfiguration, PushTemplate, PushLog
)

logger = logging.getLogger('notifications')

# Try importing Firebase Admin SDK
try:
    import firebase_admin
    from firebase_admin import credentials, messaging
    FIREBASE_AVAILABLE = True
except ImportError:
    FIREBASE_AVAILABLE = False
    logger.warning("Firebase Admin SDK not installed. Install with 'pip install firebase-admin'")

# Try importing fcm_django
try:
    from fcm_django.models import FCMDevice
    FCM_DJANGO_AVAILABLE = True
except ImportError:
    FCM_DJANGO_AVAILABLE = False
    logger.warning("fcm_django package not installed. Install with 'pip install fcm-django'")

# Try importing APNS
try:
    from apns2.client import APNsClient
    from apns2.payload import Payload
    APNS_AVAILABLE = True
except ImportError:
    APNS_AVAILABLE = False
    logger.warning("apns2 package not installed. Install with 'pip install apns2'")

User = get_user_model()


class PushNotificationService:
    """
    Centralized service for sending push notifications throughout the application.
    Consolidates functionality from integrations app.
    """
    
    def __init__(self, integration: Optional[NotificationIntegration] = None, provider: Optional[str] = None):
        """
        Initialize the push notification service with optional integration configuration.
        
        Args:
            integration: Specific push integration to use, otherwise uses default
            provider: Optional provider override
        """
        self.integration = integration
        self.config = None
        self._provider_name = provider
        
        if integration is None and provider is None:
            try:
                # Use the default push integration
                self.integration = NotificationIntegration.objects.filter(
                    integration_type='PUSH', 
                    is_active=True, 
                    is_default=True
                ).first()
                
                # If no default is found, use any active push integration
                if self.integration is None:
                    self.integration = NotificationIntegration.objects.filter(
                        integration_type='PUSH', 
                        is_active=True
                    ).first()
            except Exception as e:
                logger.error(f"Error finding push integration: {str(e)}")
                self.integration = None
        
        if self.integration:
            try:
                self.config = PushConfiguration.objects.get(integration=self.integration)
                if not provider:
                    self._provider_name = self.config.provider
            except PushConfiguration.DoesNotExist:
                logger.error(f"Push configuration not found for integration: {self.integration.name}")
    
    def send_push_notification(
        self, 
        user: User, 
        title: str, 
        body: str, 
        data: Optional[Dict[str, Any]] = None,
        image_url: Optional[str] = None,
        action_url: Optional[str] = None,
        async_send: bool = True
    ) -> Union[str, Dict[str, Any]]:
        """
        Send push notification to a user.
        
        Args:
            user: User to send notification to
            title: Notification title
            body: Notification body
            data: Optional data payload
            image_url: Optional image URL
            action_url: Optional action URL
            async_send: Whether to send asynchronously (default True)
            
        Returns:
            If async_send is True, returns the task ID.
            If async_send is False, returns a dict with status info.
        """
        # Create push log entry
        push_log = PushLog.objects.create(
            integration=self.integration,
            user=user,
            title=title,
            body=body,
            data=data,
            image_url=image_url,
            action_url=action_url,
            status='PENDING',
            provider=self._provider_name or (self.config.provider if self.config else 'UNKNOWN')
        )
        
        if async_send:
            # Send using Celery task asynchronously
            task = send_push_notification_task.delay(
                user_id=user.id,
                title=title,
                body=body,
                data=data,
                image_url=image_url,
                action_url=action_url,
                push_log_id=push_log.id,
                integration_id=self.integration.id if self.integration else None,
                provider=self._provider_name
            )
            return task.id
        else:
            # Send synchronously
            try:
                return self._send_push_notification_internal(
                    user=user,
                    title=title,
                    body=body,
                    data=data,
                    image_url=image_url,
                    action_url=action_url,
                    push_log_id=push_log.id
                )
            except Exception as e:
                logger.error(f"Error sending push notification: {str(e)}")
                push_log.status = 'FAILED'
                push_log.error_message = str(e)
                push_log.save()
                return {
                    'success': False,
                    'error': str(e),
                    'push_log_id': push_log.id
                }
    
    def _send_push_notification_internal(
        self, 
        user: User, 
        title: str, 
        body: str, 
        data: Optional[Dict[str, Any]] = None,
        image_url: Optional[str] = None,
        action_url: Optional[str] = None,
        push_log_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Internal method to send push notification (used both by sync and async sending).
        
        Args:
            user: User to send notification to
            title: Notification title
            body: Notification body
            data: Optional data payload
            image_url: Optional image URL
            action_url: Optional action URL
            push_log_id: Optional push log ID for updating status
            
        Returns:
            Dict with success status and message ID
        """
        try:
            # Get provider
            provider_name = self._provider_name or (self.config.provider if self.config else 'FIREBASE')
            
            if provider_name == 'FIREBASE':
                return self._send_firebase_notification(
                    user, title, body, data, image_url, action_url, push_log_id
                )
            elif provider_name == 'APNS':
                return self._send_apns_notification(
                    user, title, body, data, image_url, action_url, push_log_id
                )
            else:
                raise ValueError(f"Unsupported push provider: {provider_name}")
                
        except Exception as e:
            # Update log status on failure
            if push_log_id:
                with transaction.atomic():
                    push_log = PushLog.objects.get(id=push_log_id)
                    push_log.status = 'FAILED'
                    push_log.error_message = str(e)
                    push_log.save()
            
            logger.error(f"Failed to send push notification: {str(e)}")
            raise
    
    def _send_firebase_notification(
        self, 
        user: User, 
        title: str, 
        body: str, 
        data: Optional[Dict[str, Any]] = None,
        image_url: Optional[str] = None,
        action_url: Optional[str] = None,
        push_log_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Send push notification using Firebase.
        
        Args:
            user: User to send notification to
            title: Notification title
            body: Notification body
            data: Optional data payload
            image_url: Optional image URL
            action_url: Optional action URL
            push_log_id: Optional push log ID for updating status
            
        Returns:
            Dict with success status and message ID
        """
        if not FIREBASE_AVAILABLE:
            raise ImportError("Firebase Admin SDK not installed. Install with 'pip install firebase-admin'")
        
        try:
            # Initialize Firebase if not already done
            if not firebase_admin._apps:
                if self.config and self.config.firebase_credentials:
                    # Use credentials from config
                    cred = credentials.Certificate(json.loads(self.config.firebase_credentials))
                    firebase_admin.initialize_app(cred)
                else:
                    # Use default credentials
                    firebase_admin.initialize_app()
            
            # Get user's FCM devices
            if FCM_DJANGO_AVAILABLE:
                devices = FCMDevice.objects.filter(user=user, active=True)
            else:
                # Fallback: get devices from user model if it has FCM tokens
                devices = []
                if hasattr(user, 'fcm_tokens'):
                    for token in user.fcm_tokens.all():
                        devices.append(type('Device', (), {'registration_id': token.token})())
            
            if not devices:
                logger.warning(f"No FCM devices found for user {user.id}")
                return {
                    'success': False,
                    'error': 'No FCM devices found for user',
                    'push_log_id': push_log_id
                }
            
            # Prepare notification data
            notification_data = data or {}
            if action_url:
                notification_data['action_url'] = action_url
            
            # Create notification
            notification = messaging.Notification(
                title=title,
                body=body,
                image=image_url
            )
            
            # Create message
            message = messaging.MulticastMessage(
                notification=notification,
                data=notification_data,
                tokens=[device.registration_id for device in devices]
            )
            
            # Send notification
            response = messaging.send_multicast(message)
            
            # Update log status
            if push_log_id:
                with transaction.atomic():
                    push_log = PushLog.objects.get(id=push_log_id)
                    push_log.status = 'SENT' if response.success_count > 0 else 'FAILED'
                    push_log.message_id = str(response.response[0].message_id) if response.response else None
                    push_log.delivered_at = timezone.now()
                    push_log.save()
            
            logger.info(f"Firebase notification sent to {response.success_count} devices for user {user.id}")
            return {
                'success': response.success_count > 0,
                'success_count': response.success_count,
                'failure_count': response.failure_count,
                'push_log_id': push_log_id
            }
            
        except Exception as e:
            logger.error(f"Failed to send Firebase notification: {str(e)}")
            raise
    
    def _send_apns_notification(
        self, 
        user: User, 
        title: str, 
        body: str, 
        data: Optional[Dict[str, Any]] = None,
        image_url: Optional[str] = None,
        action_url: Optional[str] = None,
        push_log_id: Optional[int] = None
    ) -> Dict[str, Any]:
        """
        Send push notification using Apple Push Notification Service (APNS).
        
        Args:
            user: User to send notification to
            title: Notification title
            body: Notification body
            data: Optional data payload
            image_url: Optional image URL
            action_url: Optional action URL
            push_log_id: Optional push log ID for updating status
            
        Returns:
            Dict with success status and message ID
        """
        if not APNS_AVAILABLE:
            raise ImportError("apns2 package not installed. Install with 'pip install apns2'")
        
        try:
            # Get APNS configuration
            if not self.config:
                raise ValueError("APNS configuration not found")
            
            # Initialize APNS client
            client = APNsClient(
                self.config.apns_certificate_path,
                use_sandbox=self.config.apns_use_sandbox
            )
            
            # Get user's APNS devices
            devices = []
            if hasattr(user, 'apns_tokens'):
                for token in user.apns_tokens.all():
                    devices.append(token.token)
            
            if not devices:
                logger.warning(f"No APNS devices found for user {user.id}")
                return {
                    'success': False,
                    'error': 'No APNS devices found for user',
                    'push_log_id': push_log_id
                }
            
            # Prepare notification data
            notification_data = data or {}
            if action_url:
                notification_data['action_url'] = action_url
            
            # Create payload
            payload = Payload(
                alert=body,
                title=title,
                badge=1,
                sound='default',
                custom=notification_data
            )
            
            # Send to all devices
            success_count = 0
            failure_count = 0
            
            for device_token in devices:
                try:
                    client.send_notification(device_token, payload)
                    success_count += 1
                except Exception as e:
                    logger.error(f"Failed to send APNS notification to device {device_token}: {str(e)}")
                    failure_count += 1
            
            # Update log status
            if push_log_id:
                with transaction.atomic():
                    push_log = PushLog.objects.get(id=push_log_id)
                    push_log.status = 'SENT' if success_count > 0 else 'FAILED'
                    push_log.delivered_at = timezone.now()
                    push_log.save()
            
            logger.info(f"APNS notification sent to {success_count} devices for user {user.id}")
            return {
                'success': success_count > 0,
                'success_count': success_count,
                'failure_count': failure_count,
                'push_log_id': push_log_id
            }
            
        except Exception as e:
            logger.error(f"Failed to send APNS notification: {str(e)}")
            raise
    
    def send_template_push_notification(
        self, 
        template_name: str, 
        context: Dict[str, Any], 
        user: User, 
        async_send: bool = True
    ) -> Union[str, Dict[str, Any]]:
        """
        Send push notification using a template from the database.
        
        Args:
            template_name: Name of the push template to use
            context: Dictionary of context variables for rendering the template
            user: User to send notification to
            async_send: Whether to send asynchronously (default True)
            
        Returns:
            If async_send is True, returns the task ID.
            If async_send is False, returns a dict with status info.
        """
        try:
            # Get the template
            template = PushTemplate.objects.get(name=template_name, is_active=True)
            
            # Render title and body with context
            title = template.title
            body = template.body
            
            for key, value in context.items():
                title = title.replace(f"{{{key}}}", str(value))
                body = body.replace(f"{{{key}}}", str(value))
            
            # Prepare data
            data = template.data or {}
            for key, value in context.items():
                if isinstance(data, dict):
                    data = {k: v.replace(f"{{{key}}}", str(value)) if isinstance(v, str) else v for k, v in data.items()}
            
            # Send the push notification
            return self.send_push_notification(
                user=user,
                title=title,
                body=body,
                data=data,
                image_url=template.image_url,
                action_url=template.action_url,
                async_send=async_send
            )
        
        except PushTemplate.DoesNotExist:
            logger.error(f"Push template '{template_name}' not found")
            return {
                'success': False,
                'error': f"Push template '{template_name}' not found"
            }
        except Exception as e:
            logger.error(f"Error sending template push notification: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def send_bulk_push_notification(
        self, 
        push_data_list: List[Dict[str, Any]], 
        async_send: bool = True
    ) -> Dict[str, Any]:
        """
        Send multiple push notifications efficiently.
        
        Args:
            push_data_list: List of dictionaries with push notification parameters
            async_send: Whether to send asynchronously
            
        Returns:
            Dictionary with summary of push notification sending results
        """
        results = []
        success_count = 0
        failure_count = 0
        
        for push_data in push_data_list:
            try:
                user_id = push_data.get('user_id')
                title = push_data.get('title')
                body = push_data.get('body')
                data = push_data.get('data')
                image_url = push_data.get('image_url')
                action_url = push_data.get('action_url')
                
                # Get user
                try:
                    user = User.objects.get(id=user_id)
                except User.DoesNotExist:
                    results.append({
                        'status': 'failed',
                        'error': f'User with ID {user_id} not found',
                        'user_id': user_id
                    })
                    failure_count += 1
                    continue
                
                result = self.send_push_notification(
                    user=user,
                    title=title,
                    body=body,
                    data=data,
                    image_url=image_url,
                    action_url=action_url,
                    async_send=async_send
                )
                
                if async_send:
                    results.append({
                        'task_id': result,
                        'status': 'queued',
                        'user_id': user_id
                    })
                    success_count += 1
                else:
                    if result.get('success', False):
                        results.append({
                            'status': 'sent',
                            'user_id': user_id,
                            'push_log_id': result.get('push_log_id')
                        })
                        success_count += 1
                    else:
                        results.append({
                            'status': 'failed',
                            'error': result.get('error'),
                            'user_id': user_id,
                            'push_log_id': result.get('push_log_id')
                        })
                        failure_count += 1
                        
            except Exception as e:
                results.append({
                    'status': 'failed',
                    'error': str(e),
                    'user_id': push_data.get('user_id')
                })
                failure_count += 1
        
        return {
            'total': len(push_data_list),
            'success': success_count,
            'failed': failure_count,
            'results': results
        }
    
    def get_available_templates(self, category: Optional[str] = None) -> List[PushTemplate]:
        """
        Get available push notification templates.
        
        Args:
            category: Optional category filter
            
        Returns:
            List of PushTemplate objects
        """
        queryset = PushTemplate.objects.filter(is_active=True)
        if category:
            queryset = queryset.filter(category=category)
        return queryset.order_by('category', 'name')
    
    def create_template(
        self, 
        name: str, 
        title: str, 
        body: str, 
        category: str = "general",
        data: Optional[Dict[str, Any]] = None,
        image_url: Optional[str] = None,
        action_url: Optional[str] = None,
        description: Optional[str] = None,
        available_variables: Optional[str] = None
    ) -> PushTemplate:
        """
        Create a new push notification template.
        
        Args:
            name: Template name
            title: Notification title with {variable} placeholders
            body: Notification body with {variable} placeholders
            category: Template category
            data: Optional data payload
            image_url: Optional image URL
            action_url: Optional action URL
            description: Template description
            available_variables: Documentation of available variables
            
        Returns:
            Created PushTemplate object
        """
        return PushTemplate.objects.create(
            name=name,
            title=title,
            body=body,
            category=category,
            data=data,
            image_url=image_url,
            action_url=action_url,
            description=description,
            available_variables=available_variables
        )


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_push_notification_task(
    self, 
    user_id: int, 
    title: str, 
    body: str, 
    data: Optional[Dict[str, Any]] = None,
    image_url: Optional[str] = None,
    action_url: Optional[str] = None,
    push_log_id: Optional[int] = None, 
    integration_id: Optional[int] = None, 
    provider: Optional[str] = None
) -> Dict[str, Any]:
    """
    Celery task for sending push notifications asynchronously.
    """
    try:
        # Get user
        user = User.objects.get(id=user_id)
        
        # Initialize push service with the specified integration if provided
        if integration_id:
            try:
                integration = NotificationIntegration.objects.get(id=integration_id)
                push_service = PushNotificationService(integration=integration, provider=provider)
            except NotificationIntegration.DoesNotExist:
                push_service = PushNotificationService(provider=provider)
        else:
            push_service = PushNotificationService(provider=provider)
        
        # Send the push notification
        return push_service._send_push_notification_internal(
            user=user,
            title=title,
            body=body,
            data=data,
            image_url=image_url,
            action_url=action_url,
            push_log_id=push_log_id
        )
    
    except User.DoesNotExist:
        logger.error(f"User with ID {user_id} not found")
        return {
            'success': False,
            'error': f'User with ID {user_id} not found',
            'push_log_id': push_log_id
        }
    except Exception as e:
        logger.error(f"Error in send_push_notification_task: {str(e)}")
        
        # Update log status
        if push_log_id:
            try:
                with transaction.atomic():
                    push_log = PushLog.objects.get(id=push_log_id)
                    push_log.status = 'FAILED'
                    push_log.error_message = f"Attempt {self.request.retries + 1}: {str(e)}"
                    push_log.save()
            except Exception as log_error:
                logger.error(f"Failed to update push log: {str(log_error)}")
        
        # Retry the task if we haven't exceeded retry limits
        try:
            raise self.retry(exc=e)
        except Exception as retry_error:
            return {
                'success': False,
                'error': f"Failed after retries: {str(e)}",
                'push_log_id': push_log_id
            }
