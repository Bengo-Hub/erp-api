"""
Django management command to test notification functionality
"""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from notifications.services import (
    EmailService, SMSService, PushNotificationService, NotificationService
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Test notification functionality'

    def add_arguments(self, parser):
        parser.add_argument(
            '--user-id',
            type=int,
            help='User ID to send test notifications to',
        )
        parser.add_argument(
            '--email',
            type=str,
            help='Email address to send test email to',
        )
        parser.add_argument(
            '--phone',
            type=str,
            help='Phone number to send test SMS to',
        )
        parser.add_argument(
            '--channel',
            type=str,
            choices=['email', 'sms', 'push', 'all'],
            default='all',
            help='Notification channel to test',
        )
        parser.add_argument(
            '--template',
            type=str,
            help='Template name to use for testing',
        )

    def handle(self, *args, **options):
        self.stdout.write('Testing notification functionality...')

        # Get test user
        user = self.get_test_user(options.get('user_id'))
        
        if options['channel'] in ['email', 'all']:
            self.test_email(options.get('email'), options.get('template'))
        
        if options['channel'] in ['sms', 'all']:
            self.test_sms(options.get('phone'), options.get('template'))
        
        if options['channel'] in ['push', 'all']:
            self.test_push(user, options.get('template'))
        
        if options['channel'] == 'all':
            self.test_notification_service(user, options.get('template'))

        self.stdout.write(
            self.style.SUCCESS('Notification testing completed!')
        )

    def get_test_user(self, user_id):
        """Get test user"""
        if user_id:
            try:
                return User.objects.get(id=user_id)
            except User.DoesNotExist:
                raise CommandError(f'User with ID {user_id} not found')
        
        # Get first available user
        user = User.objects.first()
        if not user:
            raise CommandError('No users found. Please create a user first.')
        
        self.stdout.write(f'Using user: {user.username} ({user.email})')
        return user

    def test_email(self, email, template_name):
        """Test email functionality"""
        self.stdout.write('\n--- Testing Email Service ---')
        
        try:
            email_service = EmailService()
            
            if template_name:
                # Test template email
                context = {
                    'first_name': 'Test User',
                    'username': 'testuser',
                    'email': email or 'test@example.com',
                    'login_url': 'https://app.bengoerp.com/login'
                }
                
                result = email_service.send_template_email(
                    template_name=template_name,
                    context=context,
                    recipient_list=[email or 'test@example.com'],
                    async_send=False
                )
                
                if result.get('success', False):
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Template email sent successfully: {template_name}')
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'✗ Template email failed: {result.get("error")}')
                    )
            else:
                # Test direct email
                result = email_service.send_email(
                    subject='Test Email from Bengo ERP',
                    message='This is a test email to verify email functionality.',
                    recipient_list=[email or 'test@example.com'],
                    async_send=False
                )
                
                if result.get('success', False):
                    self.stdout.write(
                        self.style.SUCCESS('✓ Direct email sent successfully')
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'✗ Direct email failed: {result.get("error")}')
                    )
        
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Email test failed: {str(e)}')
            )

    def test_sms(self, phone, template_name):
        """Test SMS functionality"""
        self.stdout.write('\n--- Testing SMS Service ---')
        
        try:
            sms_service = SMSService()
            
            if template_name:
                # Test template SMS
                context = {
                    'first_name': 'Test User',
                    'approval_type': 'Purchase Order',
                    'amount': '10,000',
                    'due_date': '2024-01-15'
                }
                
                result = sms_service.send_template_sms(
                    template_name=template_name,
                    context=context,
                    to=phone or '+254700000000',
                    async_send=False
                )
                
                if result.get('success', False):
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Template SMS sent successfully: {template_name}')
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'✗ Template SMS failed: {result.get("error")}')
                    )
            else:
                # Test direct SMS
                result = sms_service.send_sms(
                    to=phone or '+254700000000',
                    message='Test SMS from Bengo ERP - SMS functionality is working!',
                    async_send=False
                )
                
                if result.get('success', False):
                    self.stdout.write(
                        self.style.SUCCESS('✓ Direct SMS sent successfully')
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'✗ Direct SMS failed: {result.get("error")}')
                    )
        
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ SMS test failed: {str(e)}')
            )

    def test_push(self, user, template_name):
        """Test push notification functionality"""
        self.stdout.write('\n--- Testing Push Notification Service ---')
        
        try:
            push_service = PushNotificationService()
            
            if template_name:
                # Test template push notification
                context = {
                    'first_name': user.first_name or 'Test User',
                    'approval_type': 'Purchase Order',
                    'amount': '10,000',
                    'due_date': '2024-01-15'
                }
                
                result = push_service.send_template_push_notification(
                    template_name=template_name,
                    context=context,
                    user=user,
                    async_send=False
                )
                
                if result.get('success', False):
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Template push notification sent successfully: {template_name}')
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'✗ Template push notification failed: {result.get("error")}')
                    )
            else:
                # Test direct push notification
                result = push_service.send_push_notification(
                    user=user,
                    title='Test Push Notification',
                    body='This is a test push notification from Bengo ERP.',
                    data={'test': True},
                    async_send=False
                )
                
                if result.get('success', False):
                    self.stdout.write(
                        self.style.SUCCESS('✓ Direct push notification sent successfully')
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f'✗ Direct push notification failed: {result.get("error")}')
                    )
        
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Push notification test failed: {str(e)}')
            )

    def test_notification_service(self, user, template_name):
        """Test the main notification service"""
        self.stdout.write('\n--- Testing Notification Service ---')
        
        try:
            notification_service = NotificationService()
            
            # Test basic notification
            result = notification_service.send_notification(
                user=user,
                title='Test Notification',
                message='This is a test notification across all channels.',
                notification_type='test',
                channels=['in_app', 'email', 'sms', 'push'],
                async_send=False
            )
            
            # Check results
            success_count = sum(1 for r in result.values() if isinstance(r, dict) and r.get('success', False))
            total_count = len(result)
            
            if success_count > 0:
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Notification sent successfully ({success_count}/{total_count} channels)')
                )
                
                for channel, channel_result in result.items():
                    if isinstance(channel_result, dict):
                        status = '✓' if channel_result.get('success', False) else '✗'
                        self.stdout.write(f'  {status} {channel}: {channel_result.get("message", "No message")}')
            else:
                self.stdout.write(
                    self.style.ERROR('✗ All notification channels failed')
                )
        
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'✗ Notification service test failed: {str(e)}')
            )
