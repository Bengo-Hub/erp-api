"""
Views for the notifications app
"""
import logging
from rest_framework import status, viewsets
from rest_framework.decorators import api_view, permission_classes, action
from rest_framework.permissions import IsAuthenticated, IsAdminUser
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q, Count, Sum
from django.http import JsonResponse

from .models import (
    NotificationIntegration, EmailConfiguration, SMSConfiguration, PushConfiguration,
    EmailTemplate, SMSTemplate, PushTemplate,
    EmailLog, SMSLog, PushLog, InAppNotification, UserNotificationPreferences
)
from .serializers import (
    NotificationIntegrationSerializer, NotificationIntegrationCreateSerializer,
    EmailConfigurationSerializer, SMSConfigurationSerializer, PushConfigurationSerializer,
    EmailTemplateSerializer, SMSTemplateSerializer, PushTemplateSerializer
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
            
            # Parse is_read query parameter from string to boolean
            # Frontend may send: ?is_read=true, ?is_read=false, ?is_read=1, ?is_read=0
            is_read_param = request.GET.get('is_read', '').lower().strip()
            is_read = None
            if is_read_param in ['true', '1', 'yes', 'on']:
                is_read = True
            elif is_read_param in ['false', '0', 'no', 'off']:
                is_read = False
            # else: is_read remains None (no filter)
            
            # Get notifications
            result = notification_service.get_user_notifications(
                user=request.user,
                limit=request.GET.get('limit', 50),
                offset=request.GET.get('offset', 0),
                notification_type=request.GET.get('notification_type'),
                is_read=is_read
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


# ===== ViewSets for Notification Settings =====

class NotificationIntegrationViewSet(viewsets.ModelViewSet):
    """
    ViewSet for managing notification integrations (Email, SMS, Push).
    Provides CRUD operations and test functionality.
    """
    queryset = NotificationIntegration.objects.all()
    permission_classes = [IsAuthenticated]

    def get_serializer_class(self):
        if self.action in ['create', 'update', 'partial_update']:
            return NotificationIntegrationCreateSerializer
        return NotificationIntegrationSerializer

    def get_queryset(self):
        queryset = NotificationIntegration.objects.all()

        # Filter by integration type
        integration_type = self.request.query_params.get('type')
        if integration_type:
            queryset = queryset.filter(integration_type=integration_type.upper())

        # Filter by active status
        is_active = self.request.query_params.get('is_active')
        if is_active is not None:
            queryset = queryset.filter(is_active=is_active.lower() == 'true')

        return queryset.order_by('integration_type', '-is_default', 'name')

    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """Test the integration by sending a test notification"""
        integration = self.get_object()
        test_recipient = request.data.get('recipient')

        if not test_recipient:
            return Response({
                'success': False,
                'error': 'recipient is required for testing'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            if integration.integration_type == 'EMAIL':
                email_service = EmailService()
                result = email_service.send_email(
                    subject='Test Email from BengoBox ERP',
                    message='This is a test email to verify your email integration is working correctly.',
                    recipient_list=[test_recipient],
                    html_message='<h2>Test Email</h2><p>This is a test email to verify your email integration is working correctly.</p><p>If you received this email, your configuration is working!</p>',
                    async_send=False  # Send synchronously for testing
                )
                return Response({
                    'success': True,
                    'message': f'Test email sent to {test_recipient}',
                    'result': result
                })

            elif integration.integration_type == 'SMS':
                sms_service = SMSService()
                result = sms_service.send_sms(
                    to=test_recipient,
                    message='Test SMS from BengoBox ERP. If you received this, your SMS integration is working!',
                    async_send=False  # Send synchronously for testing
                )
                return Response({
                    'success': True,
                    'message': f'Test SMS sent to {test_recipient}',
                    'result': result
                })

            elif integration.integration_type == 'PUSH':
                push_service = PushNotificationService()
                # For push, recipient should be user_id
                try:
                    user = User.objects.get(pk=int(test_recipient))
                    result = push_service.send_push_notification(
                        user=user,
                        title='Test Push Notification',
                        body='This is a test push notification from BengoBox ERP.',
                        async_send=False
                    )
                    return Response({
                        'success': True,
                        'message': f'Test push notification sent to user {user.username}',
                        'result': result
                    })
                except User.DoesNotExist:
                    return Response({
                        'success': False,
                        'error': f'User with ID {test_recipient} not found'
                    }, status=status.HTTP_400_BAD_REQUEST)
            else:
                return Response({
                    'success': False,
                    'error': f'Unknown integration type: {integration.integration_type}'
                }, status=status.HTTP_400_BAD_REQUEST)

        except Exception as e:
            logger.error(f"Error testing integration {integration.name}: {str(e)}")
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @action(detail=True, methods=['post'])
    def set_default(self, request, pk=None):
        """Set this integration as the default for its type"""
        integration = self.get_object()
        integration.is_default = True
        integration.save()  # The model's save method handles unsetting other defaults

        return Response({
            'success': True,
            'message': f'{integration.name} is now the default {integration.get_integration_type_display()} integration'
        })

    @action(detail=False, methods=['get'])
    def status(self, request):
        """Get status overview of all integrations"""
        integrations = self.get_queryset()

        status_data = {
            'EMAIL': {'configured': False, 'active': False, 'default': None},
            'SMS': {'configured': False, 'active': False, 'default': None},
            'PUSH': {'configured': False, 'active': False, 'default': None},
        }

        for integration in integrations:
            int_type = integration.integration_type
            if int_type in status_data:
                status_data[int_type]['configured'] = True
                if integration.is_active:
                    status_data[int_type]['active'] = True
                if integration.is_default:
                    status_data[int_type]['default'] = {
                        'id': integration.id,
                        'name': integration.name
                    }

        return Response({
            'success': True,
            'status': status_data
        })


class EmailConfigurationViewSet(viewsets.ModelViewSet):
    """ViewSet for Email Configuration"""
    queryset = EmailConfiguration.objects.all()
    serializer_class = EmailConfigurationSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """Test email configuration by sending a test email"""
        config = self.get_object()
        test_email = request.data.get('email')

        if not test_email:
            return Response({
                'success': False,
                'error': 'email address is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            email_service = EmailService()
            result = email_service.send_email(
                subject='Test Email - Configuration Verification',
                message='This is a test email to verify your email configuration.',
                recipient_list=[test_email],
                html_message='<h2>Email Configuration Test</h2><p>Your email configuration is working correctly!</p>',
                async_send=False
            )
            return Response({
                'success': True,
                'message': f'Test email sent to {test_email}',
                'result': result
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class SMSConfigurationViewSet(viewsets.ModelViewSet):
    """ViewSet for SMS Configuration"""
    queryset = SMSConfiguration.objects.all()
    serializer_class = SMSConfigurationSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=True, methods=['post'])
    def test(self, request, pk=None):
        """Test SMS configuration by sending a test SMS"""
        config = self.get_object()
        test_phone = request.data.get('phone')

        if not test_phone:
            return Response({
                'success': False,
                'error': 'phone number is required'
            }, status=status.HTTP_400_BAD_REQUEST)

        try:
            sms_service = SMSService()
            result = sms_service.send_sms(
                to=test_phone,
                message='Test SMS from BengoBox ERP. Your SMS configuration is working!',
                async_send=False
            )
            return Response({
                'success': True,
                'message': f'Test SMS sent to {test_phone}',
                'result': result
            })
        except Exception as e:
            return Response({
                'success': False,
                'error': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class PushConfigurationViewSet(viewsets.ModelViewSet):
    """ViewSet for Push Configuration"""
    queryset = PushConfiguration.objects.all()
    serializer_class = PushConfigurationSerializer
    permission_classes = [IsAuthenticated]


class EmailTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for Email Templates"""
    queryset = EmailTemplate.objects.all()
    serializer_class = EmailTemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = EmailTemplate.objects.all()
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        return queryset.order_by('category', 'name')


class SMSTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for SMS Templates"""
    queryset = SMSTemplate.objects.all()
    serializer_class = SMSTemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = SMSTemplate.objects.all()
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        return queryset.order_by('category', 'name')


class PushTemplateViewSet(viewsets.ModelViewSet):
    """ViewSet for Push Templates"""
    queryset = PushTemplate.objects.all()
    serializer_class = PushTemplateSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = PushTemplate.objects.all()
        category = self.request.query_params.get('category')
        if category:
            queryset = queryset.filter(category=category)
        return queryset.order_by('category', 'name')