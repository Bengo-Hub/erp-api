"""
Views for the notifications app
"""
import logging
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q, Count, Sum
from django.http import JsonResponse

from .models import (
    NotificationIntegration, EmailTemplate, SMSTemplate, PushTemplate,
    EmailLog, SMSLog, PushLog, InAppNotification, UserNotificationPreferences,
    NotificationAnalytics
)
from .services import (
    EmailService, SMSService, PushNotificationService, NotificationService
)

logger = logging.getLogger('notifications')
User = get_user_model()


class SendEmailView(APIView):
    """Send email notification"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            data = request.data
            email_service = EmailService()
            
            # Send email
            result = email_service.send_email(
                subject=data.get('subject'),
                message=data.get('message'),
                recipient_list=data.get('recipients', []),
                html_message=data.get('html_message'),
                from_email=data.get('from_email'),
                cc=data.get('cc'),
                bcc=data.get('bcc'),
                reply_to=data.get('reply_to'),
                attachments=data.get('attachments'),
                async_send=data.get('async_send', True)
            )
            
            return Response({
                'success': True,
                'message': 'Email sent successfully',
                'result': result
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error sending email: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendSMSView(APIView):
    """Send SMS notification"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            data = request.data
            sms_service = SMSService()
            
            # Send SMS
            result = sms_service.send_sms(
                to=data.get('to'),
                message=data.get('message'),
                async_send=data.get('async_send', True),
                sender=data.get('sender')
            )
            
            return Response({
                'success': True,
                'message': 'SMS sent successfully',
                'result': result
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error sending SMS: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendPushView(APIView):
    """Send push notification"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            data = request.data
            push_service = PushNotificationService()
            
            # Get user
            user_id = data.get('user_id')
            if not user_id:
                return Response({
                    'success': False,
                    'error': 'user_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            user = get_object_or_404(User, id=user_id)
            
            # Send push notification
            result = push_service.send_push_notification(
                user=user,
                title=data.get('title'),
                body=data.get('body'),
                data=data.get('data'),
                image_url=data.get('image_url'),
                action_url=data.get('action_url'),
                async_send=data.get('async_send', True)
            )
            
            return Response({
                'success': True,
                'message': 'Push notification sent successfully',
                'result': result
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error sending push notification: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SendNotificationView(APIView):
    """Send notification across multiple channels"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            data = request.data
            notification_service = NotificationService()
            
            # Get user
            user_id = data.get('user_id')
            if not user_id:
                return Response({
                    'success': False,
                    'error': 'user_id is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            user = get_object_or_404(User, id=user_id)
            
            # Send notification
            result = notification_service.send_notification(
                user=user,
                title=data.get('title'),
                message=data.get('message'),
                notification_type=data.get('notification_type', 'general'),
                channels=data.get('channels', ['in_app', 'email', 'sms', 'push']),
                data=data.get('data'),
                image_url=data.get('image_url'),
                action_url=data.get('action_url'),
                email_subject=data.get('email_subject'),
                email_template=data.get('email_template'),
                sms_template=data.get('sms_template'),
                push_template=data.get('push_template'),
                context=data.get('context'),
                async_send=data.get('async_send', True)
            )
            
            return Response({
                'success': True,
                'message': 'Notification sent successfully',
                'result': result
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error sending notification: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class BulkNotificationView(APIView):
    """Send bulk notifications"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            data = request.data
            notification_service = NotificationService()
            
            notification_data_list = data.get('notifications', [])
            if not notification_data_list:
                return Response({
                    'success': False,
                    'error': 'notifications list is required'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Send bulk notifications
            result = notification_service.send_bulk_notification(
                notification_data_list=notification_data_list,
                async_send=data.get('async_send', True)
            )
            
            return Response({
                'success': True,
                'message': 'Bulk notifications sent successfully',
                'result': result
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error sending bulk notifications: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class TestNotificationView(APIView):
    """Test notification configuration"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            data = request.data
            notification_service = NotificationService()
            
            # Get user
            user_id = data.get('user_id', request.user.id)
            user = get_object_or_404(User, id=user_id)
            
            # Test notification
            result = notification_service.test_notification(
                user=user,
                channels=data.get('channels'),
                test_type=data.get('test_type', 'basic')
            )
            
            return Response({
                'success': True,
                'message': 'Test notification completed',
                'result': result
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error testing notification: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class InAppNotificationListView(APIView):
    """Get user's in-app notifications"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            notification_service = NotificationService()
            
            # Get notifications
            result = notification_service.get_user_notifications(
                user=request.user,
                limit=request.GET.get('limit', 50),
                offset=request.GET.get('offset', 0),
                notification_type=request.GET.get('notification_type'),
                is_read=request.GET.get('is_read')
            )
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting user notifications: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MarkNotificationReadView(APIView):
    """Mark a notification as read"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request, notification_id):
        try:
            notification_service = NotificationService()
            
            # Mark notification as read
            result = notification_service.mark_notification_read(
                user=request.user,
                notification_id=notification_id
            )
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error marking notification as read: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class MarkAllNotificationsReadView(APIView):
    """Mark all notifications as read"""
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            notification_service = NotificationService()
            
            # Mark all notifications as read
            result = notification_service.mark_all_notifications_read(
                user=request.user
            )
            
            return Response(result, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error marking all notifications as read: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Additional views for templates, logs, analytics, etc. would go here
# For brevity, I'll include the key ones

class EmailTemplateListView(APIView):
    """Get email templates"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            email_service = EmailService()
            templates = email_service.get_available_templates(
                category=request.GET.get('category')
            )
            
            return Response({
                'templates': [
                    {
                        'id': t.id,
                        'name': t.name,
                        'subject': t.subject,
                        'category': t.category,
                        'description': t.description,
                        'available_variables': t.available_variables
                    }
                    for t in templates
                ]
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting email templates: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SMSTemplateListView(APIView):
    """Get SMS templates"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            sms_service = SMSService()
            templates = sms_service.get_available_templates(
                category=request.GET.get('category')
            )
            
            return Response({
                'templates': [
                    {
                        'id': t.id,
                        'name': t.name,
                        'content': t.content,
                        'category': t.category,
                        'description': t.description,
                        'available_variables': t.available_variables
                    }
                    for t in templates
                ]
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting SMS templates: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PushTemplateListView(APIView):
    """Get push notification templates"""
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        try:
            push_service = PushNotificationService()
            templates = push_service.get_available_templates(
                category=request.GET.get('category')
            )
            
            return Response({
                'templates': [
                    {
                        'id': t.id,
                        'name': t.name,
                        'title': t.title,
                        'body': t.body,
                        'category': t.category,
                        'description': t.description,
                        'available_variables': t.available_variables
                    }
                    for t in templates
                ]
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error getting push templates: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# Webhook views
class EmailBounceWebhookView(APIView):
    """Handle email bounce webhooks"""
    
    def post(self, request):
        try:
            data = request.data
            logger.info(f"Email bounce webhook received: {data}")
            return Response({'success': True}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error processing email bounce webhook: {str(e)}")
            return Response({'success': False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class EmailComplaintWebhookView(APIView):
    """Handle email complaint webhooks"""
    
    def post(self, request):
        try:
            data = request.data
            logger.info(f"Email complaint webhook received: {data}")
            return Response({'success': True}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error processing email complaint webhook: {str(e)}")
            return Response({'success': False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SMSDeliveryWebhookView(APIView):
    """Handle SMS delivery webhooks"""
    
    def post(self, request):
        try:
            data = request.data
            logger.info(f"SMS delivery webhook received: {data}")
            return Response({'success': True}, status=status.HTTP_200_OK)
        except Exception as e:
            logger.error(f"Error processing SMS delivery webhook: {str(e)}")
            return Response({'success': False}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)