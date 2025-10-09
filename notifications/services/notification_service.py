"""
Centralized Notification Service
Orchestrates all notification channels (email, SMS, push, in-app)
Consolidates functionality from integrations app
"""
import logging
from typing import List, Dict, Any, Optional, Union
from django.db import transaction
from django.utils import timezone
from django.contrib.auth import get_user_model
from celery import shared_task

from ..models import (
    NotificationIntegration, UserNotificationPreferences, InAppNotification,
    NotificationAnalytics, NotificationTest
)
from .email_service import EmailService
from .sms_service import SMSService
from .push_service import PushNotificationService

logger = logging.getLogger('notifications')

User = get_user_model()


class NotificationService:
    """
    Centralized service for sending notifications across all channels.
    Consolidates functionality from integrations app.
    """
    
    def __init__(self, integration: Optional[NotificationIntegration] = None):
        """
        Initialize the notification service with optional integration configuration.
        
        Args:
            integration: Specific notification integration to use, otherwise uses default
        """
        self.integration = integration
        self.email_service = None
        self.sms_service = None
        self.push_service = None
        
        if integration is None:
            try:
                # Use the default notification integration
                self.integration = NotificationIntegration.objects.filter(
                    integration_type='NOTIFICATION', 
                    is_active=True, 
                    is_default=True
                ).first()
                
                # If no default is found, use any active notification integration
                if self.integration is None:
                    self.integration = NotificationIntegration.objects.filter(
                        integration_type='NOTIFICATION', 
                        is_active=True
                    ).first()
            except Exception as e:
                logger.error(f"Error finding notification integration: {str(e)}")
                self.integration = None
        
        # Initialize channel services
        self._initialize_services()
    
    def _initialize_services(self):
        """Initialize email, SMS, and push notification services."""
        try:
            # Initialize email service
            self.email_service = EmailService(integration=self.integration)
        except Exception as e:
            logger.warning(f"Failed to initialize email service: {str(e)}")
            self.email_service = None
        
        try:
            # Initialize SMS service
            self.sms_service = SMSService(integration=self.integration)
        except Exception as e:
            logger.warning(f"Failed to initialize SMS service: {str(e)}")
            self.sms_service = None
        
        try:
            # Initialize push service
            self.push_service = PushNotificationService(integration=self.integration)
        except Exception as e:
            logger.warning(f"Failed to initialize push service: {str(e)}")
            self.push_service = None
    
    def send_notification(
        self, 
        user: User, 
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
        **kwargs
    ) -> Dict[str, Any]:
        """
        Send notification across multiple channels.
        
        Args:
            user: User to send notification to
            title: Notification title
            message: Notification message
            notification_type: Type of notification (e.g., 'payroll', 'approval', 'general')
            channels: List of channels to use (e.g., ['email', 'sms', 'push', 'in_app'])
            data: Optional data payload
            image_url: Optional image URL
            action_url: Optional action URL
            email_subject: Optional email subject override
            email_template: Optional email template name
            sms_template: Optional SMS template name
            push_template: Optional push template name
            context: Optional context variables for templates
            async_send: Whether to send asynchronously (default True)
            **kwargs: Additional channel-specific parameters
            
        Returns:
            Dictionary with results from each channel
        """
        # Default to all available channels if not specified
        if channels is None:
            channels = ['in_app', 'email', 'sms', 'push']
        
        # Get user preferences
        user_preferences = self._get_user_preferences(user)
        
        # Filter channels based on user preferences
        enabled_channels = self._filter_enabled_channels(channels, user_preferences)
        
        # Prepare context for templates
        template_context = context or {}
        template_context.update({
            'username': user.username,
            'first_name': getattr(user, 'first_name', ''),
            'last_name': getattr(user, 'last_name', ''),
            'full_name': f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip(),
            'email': user.email,
            'title': title,
            'message': message,
            'notification_type': notification_type,
            'action_url': action_url,
            'image_url': image_url
        })
        
        results = {}
        
        # Send in-app notification
        if 'in_app' in enabled_channels:
            try:
                in_app_result = self._send_in_app_notification(
                    user, title, message, notification_type, data, image_url, action_url
                )
                results['in_app'] = in_app_result
            except Exception as e:
                logger.error(f"Failed to send in-app notification: {str(e)}")
                results['in_app'] = {'success': False, 'error': str(e)}
        
        # Send email notification
        if 'email' in enabled_channels and self.email_service:
            try:
                email_result = self._send_email_notification(
                    user, title, message, email_subject, email_template, template_context, **kwargs
                )
                results['email'] = email_result
            except Exception as e:
                logger.error(f"Failed to send email notification: {str(e)}")
                results['email'] = {'success': False, 'error': str(e)}
        
        # Send SMS notification
        if 'sms' in enabled_channels and self.sms_service:
            try:
                sms_result = self._send_sms_notification(
                    user, message, sms_template, template_context, **kwargs
                )
                results['sms'] = sms_result
            except Exception as e:
                logger.error(f"Failed to send SMS notification: {str(e)}")
                results['sms'] = {'success': False, 'error': str(e)}
        
        # Send push notification
        if 'push' in enabled_channels and self.push_service:
            try:
                push_result = self._send_push_notification(
                    user, title, message, data, image_url, action_url, push_template, template_context, **kwargs
                )
                results['push'] = push_result
            except Exception as e:
                logger.error(f"Failed to send push notification: {str(e)}")
                results['push'] = {'success': False, 'error': str(e)}
        
        # Update analytics
        self._update_analytics(user, notification_type, results)
        
        return results
    
    def _get_user_preferences(self, user: User) -> Optional[UserNotificationPreferences]:
        """Get user notification preferences."""
        try:
            return UserNotificationPreferences.objects.get(user=user)
        except UserNotificationPreferences.DoesNotExist:
            return None
    
    def _filter_enabled_channels(self, channels: List[str], preferences: Optional[UserNotificationPreferences]) -> List[str]:
        """Filter channels based on user preferences."""
        if not preferences:
            return channels
        
        enabled_channels = []
        for channel in channels:
            if channel == 'email' and preferences.email_enabled:
                enabled_channels.append(channel)
            elif channel == 'sms' and preferences.sms_enabled:
                enabled_channels.append(channel)
            elif channel == 'push' and preferences.push_enabled:
                enabled_channels.append(channel)
            elif channel == 'in_app' and preferences.in_app_enabled:
                enabled_channels.append(channel)
        
        return enabled_channels
    
    def _send_in_app_notification(
        self, 
        user: User, 
        title: str, 
        message: str, 
        notification_type: str,
        data: Optional[Dict[str, Any]] = None,
        image_url: Optional[str] = None,
        action_url: Optional[str] = None
    ) -> Dict[str, Any]:
        """Send in-app notification."""
        try:
            # Create in-app notification
            notification = InAppNotification.objects.create(
                user=user,
                title=title,
                message=message,
                notification_type=notification_type,
                data=data,
                image_url=image_url,
                action_url=action_url,
                is_read=False
            )
            
            logger.info(f"In-app notification created for user {user.id}: {title}")
            return {
                'success': True,
                'notification_id': notification.id,
                'message': 'In-app notification created successfully'
            }
            
        except Exception as e:
            logger.error(f"Failed to create in-app notification: {str(e)}")
            raise
    
    def _send_email_notification(
        self, 
        user: User, 
        title: str, 
        message: str, 
        subject: Optional[str] = None,
        template_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send email notification."""
        try:
            if template_name:
                # Use template
                result = self.email_service.send_template_email(
                    template_name=template_name,
                    context=context or {},
                    recipient_list=[user.email],
                    **kwargs
                )
            else:
                # Send direct email
                result = self.email_service.send_email(
                    subject=subject or title,
                    message=message,
                    recipient_list=[user.email],
                    **kwargs
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send email notification: {str(e)}")
            raise
    
    def _send_sms_notification(
        self, 
        user: User, 
        message: str, 
        template_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send SMS notification."""
        try:
            # Get user's phone number
            phone_number = getattr(user, 'phone_number', None)
            if not phone_number:
                return {
                    'success': False,
                    'error': 'User phone number not available'
                }
            
            if template_name:
                # Use template
                result = self.sms_service.send_template_sms(
                    template_name=template_name,
                    context=context or {},
                    to=phone_number,
                    **kwargs
                )
            else:
                # Send direct SMS
                result = self.sms_service.send_sms(
                    to=phone_number,
                    message=message,
                    **kwargs
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send SMS notification: {str(e)}")
            raise
    
    def _send_push_notification(
        self, 
        user: User, 
        title: str, 
        message: str, 
        data: Optional[Dict[str, Any]] = None,
        image_url: Optional[str] = None,
        action_url: Optional[str] = None,
        template_name: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Dict[str, Any]:
        """Send push notification."""
        try:
            if template_name:
                # Use template
                result = self.push_service.send_template_push_notification(
                    template_name=template_name,
                    context=context or {},
                    user=user,
                    **kwargs
                )
            else:
                # Send direct push notification
                result = self.push_service.send_push_notification(
                    user=user,
                    title=title,
                    body=message,
                    data=data,
                    image_url=image_url,
                    action_url=action_url,
                    **kwargs
                )
            
            return result
            
        except Exception as e:
            logger.error(f"Failed to send push notification: {str(e)}")
            raise
    
    def _update_analytics(self, user: User, notification_type: str, results: Dict[str, Any]):
        """Update notification analytics."""
        try:
            # Get or create analytics record for today
            today = timezone.now().date()
            analytics, created = NotificationAnalytics.objects.get_or_create(
                date=today,
                notification_type=notification_type,
                defaults={
                    'total_sent': 0,
                    'email_sent': 0,
                    'sms_sent': 0,
                    'push_sent': 0,
                    'in_app_sent': 0,
                    'email_failed': 0,
                    'sms_failed': 0,
                    'push_failed': 0,
                    'in_app_failed': 0
                }
            )
            
            # Update counts
            analytics.total_sent += 1
            
            for channel, result in results.items():
                if result.get('success', False):
                    if channel == 'email':
                        analytics.email_sent += 1
                    elif channel == 'sms':
                        analytics.sms_sent += 1
                    elif channel == 'push':
                        analytics.push_sent += 1
                    elif channel == 'in_app':
                        analytics.in_app_sent += 1
                else:
                    if channel == 'email':
                        analytics.email_failed += 1
                    elif channel == 'sms':
                        analytics.sms_failed += 1
                    elif channel == 'push':
                        analytics.push_failed += 1
                    elif channel == 'in_app':
                        analytics.in_app_failed += 1
            
            analytics.save()
            
        except Exception as e:
            logger.error(f"Failed to update analytics: {str(e)}")
    
    def send_bulk_notification(
        self, 
        notification_data_list: List[Dict[str, Any]], 
        async_send: bool = True
    ) -> Dict[str, Any]:
        """
        Send multiple notifications efficiently.
        
        Args:
            notification_data_list: List of dictionaries with notification parameters
            async_send: Whether to send asynchronously
            
        Returns:
            Dictionary with summary of notification sending results
        """
        results = []
        success_count = 0
        failure_count = 0
        
        for notification_data in notification_data_list:
            try:
                user_id = notification_data.get('user_id')
                title = notification_data.get('title')
                message = notification_data.get('message')
                notification_type = notification_data.get('notification_type', 'general')
                channels = notification_data.get('channels', ['in_app', 'email', 'sms', 'push'])
                
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
                
                # Send notification
                result = self.send_notification(
                    user=user,
                    title=title,
                    message=message,
                    notification_type=notification_type,
                    channels=channels,
                    async_send=async_send,
                    **{k: v for k, v in notification_data.items() if k not in ['user_id', 'title', 'message', 'notification_type', 'channels']}
                )
                
                if async_send:
                    results.append({
                        'status': 'queued',
                        'user_id': user_id,
                        'channels': channels
                    })
                    success_count += 1
                else:
                    # Check if any channel succeeded
                    any_success = any(r.get('success', False) for r in result.values() if isinstance(r, dict))
                    if any_success:
                        results.append({
                            'status': 'sent',
                            'user_id': user_id,
                            'channels': channels,
                            'results': result
                        })
                        success_count += 1
                    else:
                        results.append({
                            'status': 'failed',
                            'user_id': user_id,
                            'channels': channels,
                            'results': result
                        })
                        failure_count += 1
                        
            except Exception as e:
                results.append({
                    'status': 'failed',
                    'error': str(e),
                    'user_id': notification_data.get('user_id')
                })
                failure_count += 1
        
        return {
            'total': len(notification_data_list),
            'success': success_count,
            'failed': failure_count,
            'results': results
        }
    
    def test_notification(
        self, 
        user: User, 
        channels: List[str] = None,
        test_type: str = "basic"
    ) -> Dict[str, Any]:
        """
        Send test notification to verify configuration.
        
        Args:
            user: User to send test notification to
            channels: Channels to test (default: all available)
            test_type: Type of test ('basic', 'template', 'bulk')
            
        Returns:
            Dictionary with test results
        """
        if channels is None:
            channels = ['in_app', 'email', 'sms', 'push']
        
        # Create test record
        test_record = NotificationTest.objects.create(
            user=user,
            test_type=test_type,
            channels=channels,
            status='RUNNING'
        )
        
        try:
            if test_type == 'basic':
                # Send basic test notification
                result = self.send_notification(
                    user=user,
                    title="Test Notification",
                    message="This is a test notification to verify your notification settings.",
                    notification_type="test",
                    channels=channels,
                    async_send=False
                )
            elif test_type == 'template':
                # Send template test notification
                result = self.send_notification(
                    user=user,
                    title="Template Test",
                    message="Testing template functionality",
                    notification_type="test",
                    channels=channels,
                    email_template="test_email",
                    sms_template="test_sms",
                    push_template="test_push",
                    context={'test_variable': 'Test Value'},
                    async_send=False
                )
            elif test_type == 'bulk':
                # Send bulk test notification
                result = self.send_bulk_notification(
                    notification_data_list=[{
                        'user_id': user.id,
                        'title': 'Bulk Test',
                        'message': 'Testing bulk notification functionality',
                        'notification_type': 'test',
                        'channels': channels
                    }],
                    async_send=False
                )
            else:
                raise ValueError(f"Unknown test type: {test_type}")
            
            # Update test record
            test_record.status = 'COMPLETED'
            test_record.results = result
            test_record.completed_at = timezone.now()
            test_record.save()
            
            return {
                'success': True,
                'test_id': test_record.id,
                'results': result
            }
            
        except Exception as e:
            # Update test record with error
            test_record.status = 'FAILED'
            test_record.error_message = str(e)
            test_record.completed_at = timezone.now()
            test_record.save()
            
            logger.error(f"Test notification failed: {str(e)}")
            return {
                'success': False,
                'test_id': test_record.id,
                'error': str(e)
            }
    
    def get_user_notifications(
        self, 
        user: User, 
        limit: int = 50, 
        offset: int = 0,
        notification_type: Optional[str] = None,
        is_read: Optional[bool] = None
    ) -> Dict[str, Any]:
        """
        Get user's in-app notifications.
        
        Args:
            user: User to get notifications for
            limit: Maximum number of notifications to return
            offset: Number of notifications to skip
            notification_type: Optional notification type filter
            is_read: Optional read status filter
            
        Returns:
            Dictionary with notifications and metadata
        """
        try:
            queryset = InAppNotification.objects.filter(user=user)
            
            if notification_type:
                queryset = queryset.filter(notification_type=notification_type)
            
            if is_read is not None:
                queryset = queryset.filter(is_read=is_read)
            
            total_count = queryset.count()
            notifications = queryset.order_by('-created_at')[offset:offset + limit]
            
            return {
                'notifications': [
                    {
                        'id': n.id,
                        'title': n.title,
                        'message': n.message,
                        'notification_type': n.notification_type,
                        'data': n.data,
                        'image_url': n.image_url,
                        'action_url': n.action_url,
                        'is_read': n.is_read,
                        'created_at': n.created_at,
                        'read_at': n.read_at
                    }
                    for n in notifications
                ],
                'total_count': total_count,
                'limit': limit,
                'offset': offset
            }
            
        except Exception as e:
            logger.error(f"Failed to get user notifications: {str(e)}")
            return {
                'notifications': [],
                'total_count': 0,
                'error': str(e)
            }
    
    def mark_notification_read(self, user: User, notification_id: int) -> Dict[str, Any]:
        """
        Mark a notification as read.
        
        Args:
            user: User who owns the notification
            notification_id: ID of the notification to mark as read
            
        Returns:
            Dictionary with success status
        """
        try:
            notification = InAppNotification.objects.get(id=notification_id, user=user)
            notification.is_read = True
            notification.read_at = timezone.now()
            notification.save()
            
            return {
                'success': True,
                'message': 'Notification marked as read'
            }
            
        except InAppNotification.DoesNotExist:
            return {
                'success': False,
                'error': 'Notification not found'
            }
        except Exception as e:
            logger.error(f"Failed to mark notification as read: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }
    
    def mark_all_notifications_read(self, user: User) -> Dict[str, Any]:
        """
        Mark all notifications as read for a user.
        
        Args:
            user: User to mark notifications for
            
        Returns:
            Dictionary with success status
        """
        try:
            updated_count = InAppNotification.objects.filter(
                user=user, 
                is_read=False
            ).update(
                is_read=True,
                read_at=timezone.now()
            )
            
            return {
                'success': True,
                'message': f'{updated_count} notifications marked as read'
            }
            
        except Exception as e:
            logger.error(f"Failed to mark all notifications as read: {str(e)}")
            return {
                'success': False,
                'error': str(e)
            }


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_notification_task(
    self, 
    user_id: int, 
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
    integration_id: Optional[int] = None,
    **kwargs
) -> Dict[str, Any]:
    """
    Celery task for sending notifications asynchronously.
    """
    try:
        # Get user
        user = User.objects.get(id=user_id)
        
        # Initialize notification service with the specified integration if provided
        if integration_id:
            try:
                integration = NotificationIntegration.objects.get(id=integration_id)
                notification_service = NotificationService(integration=integration)
            except NotificationIntegration.DoesNotExist:
                notification_service = NotificationService()
        else:
            notification_service = NotificationService()
        
        # Send the notification
        return notification_service.send_notification(
            user=user,
            title=title,
            message=message,
            notification_type=notification_type,
            channels=channels,
            data=data,
            image_url=image_url,
            action_url=action_url,
            email_subject=email_subject,
            email_template=email_template,
            sms_template=sms_template,
            push_template=push_template,
            context=context,
            async_send=False,  # Already running asynchronously
            **kwargs
        )
    
    except User.DoesNotExist:
        logger.error(f"User with ID {user_id} not found")
        return {
            'success': False,
            'error': f'User with ID {user_id} not found'
        }
    except Exception as e:
        logger.error(f"Error in send_notification_task: {str(e)}")
        
        # Retry the task if we haven't exceeded retry limits
        try:
            raise self.retry(exc=e)
        except Exception as retry_error:
            return {
                'success': False,
                'error': f"Failed after retries: {str(e)}"
            }
