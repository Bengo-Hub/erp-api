"""
Django management command to set up notification integrations and templates
"""
from django.core.management.base import BaseCommand, CommandError
from django.contrib.auth import get_user_model
from notifications.models import (
    NotificationIntegration, EmailConfiguration, SMSConfiguration, 
    PushConfiguration, EmailTemplate, SMSTemplate, PushTemplate
)

User = get_user_model()


class Command(BaseCommand):
    help = 'Set up notification integrations and default templates'

    def add_arguments(self, parser):
        parser.add_argument(
            '--reset',
            action='store_true',
            help='Reset all notification configurations',
        )
        parser.add_argument(
            '--templates-only',
            action='store_true',
            help='Only create templates, skip integrations',
        )

    def handle(self, *args, **options):
        if options['reset']:
            self.stdout.write('Resetting notification configurations...')
            self.reset_configurations()
            return

        if not options['templates_only']:
            self.stdout.write('Setting up notification integrations...')
            self.setup_integrations()

        self.stdout.write('Creating default templates...')
        self.create_templates()

        self.stdout.write(
            self.style.SUCCESS('Notification setup completed successfully!')
        )

    def reset_configurations(self):
        """Reset all notification configurations"""
        NotificationIntegration.objects.all().delete()
        EmailConfiguration.objects.all().delete()
        SMSConfiguration.objects.all().delete()
        PushConfiguration.objects.all().delete()
        EmailTemplate.objects.all().delete()
        SMSTemplate.objects.all().delete()
        PushTemplate.objects.all().delete()
        
        self.stdout.write(
            self.style.WARNING('All notification configurations have been reset.')
        )

    def setup_integrations(self):
        """Set up default notification integrations"""
        # Email Integration - SMTP
        email_integration, created = NotificationIntegration.objects.get_or_create(
            name='Default SMTP Email',
            integration_type='EMAIL',
            defaults={
                'is_active': True,
                'is_default': True,
                'priority': 1
            }
        )
        
        if created:
            EmailConfiguration.objects.create(
                integration=email_integration,
                provider='SMTP',
                from_email='noreply@bengoerp.com',
                from_name='Bengo ERP',
                smtp_host='smtp.gmail.com',
                smtp_port=587,
                use_tls=True,
                fail_silently=False,
                timeout=60
            )
            self.stdout.write('✓ Created default SMTP email integration')

        # SMS Integration - Twilio
        sms_integration, created = NotificationIntegration.objects.get_or_create(
            name='Default Twilio SMS',
            integration_type='SMS',
            defaults={
                'is_active': True,
                'is_default': True,
                'priority': 1
            }
        )
        
        if created:
            SMSConfiguration.objects.create(
                integration=sms_integration,
                provider='TWILIO',
                account_sid='',
                auth_token='',
                from_number='',
                api_key='',
                api_username=''
            )
            self.stdout.write('✓ Created default Twilio SMS integration')

        # Push Integration - Firebase
        push_integration, created = NotificationIntegration.objects.get_or_create(
            name='Default Firebase Push',
            integration_type='PUSH',
            defaults={
                'is_active': True,
                'is_default': True,
                'priority': 1
            }
        )
        
        if created:
            PushConfiguration.objects.create(
                integration=push_integration,
                provider='FIREBASE',
                firebase_server_key='',
                firebase_project_id=''
            )
            self.stdout.write('✓ Created default Firebase push integration')

    def create_templates(self):
        """Create default notification templates"""
        # Email Templates
        email_templates = [
            {
                'name': 'welcome_email',
                'subject': 'Welcome to Bengo ERP - {first_name}!',
                'body_html': 'Welcome to Bengo ERP! Your account has been created successfully.',
                'body_text': 'Welcome to Bengo ERP! Your account has been created successfully.',
                'category': 'user_management',
                'description': 'Welcome email for new users',
                'available_variables': 'username, first_name, last_name, email, login_url'
            },
            {
                'name': 'password_reset',
                'subject': 'Password Reset Request - Bengo ERP',
                'body_html': 'You requested a password reset. Click the link to reset your password.',
                'body_text': 'You requested a password reset. Click the link to reset your password.',
                'category': 'user_management',
                'description': 'Password reset email',
                'available_variables': 'first_name, reset_url, expiry_hours'
            },
            {
                'name': 'payroll_approval',
                'subject': 'Payroll Approval Required - {employee_name}',
                'body_html': 'A payroll approval requires your attention.',
                'body_text': 'A payroll approval requires your attention.',
                'category': 'payroll',
                'description': 'Payroll approval notification',
                'available_variables': 'approver_name, employee_name, amount, action_url'
            },
            {
                'name': 'payslip_generated',
                'subject': 'Your Payslip is Ready - {pay_period}',
                'body_html': 'Your payslip has been generated and is ready for review.',
                'body_text': 'Your payslip has been generated and is ready for review.',
                'category': 'payroll',
                'description': 'Payslip generation notification',
                'available_variables': 'employee_name, pay_period, gross_pay, net_pay, payslip_url'
            }
        ]

        for template_data in email_templates:
            template, created = EmailTemplate.objects.get_or_create(
                name=template_data['name'],
                defaults=template_data
            )
            if created:
                self.stdout.write(f'✓ Created email template: {template_data["name"]}')

        # SMS Templates
        sms_templates = [
            {
                'name': 'welcome_sms',
                'content': 'Welcome to Bengo ERP! Your account is ready. Login: {login_url}',
                'category': 'user_management',
                'description': 'Welcome SMS for new users',
                'available_variables': 'first_name, login_url'
            },
            {
                'name': 'approval_reminder',
                'content': 'Reminder: {approval_type} approval pending for {amount}. Due: {due_date}',
                'category': 'approvals',
                'description': 'Approval reminder SMS',
                'available_variables': 'approver_name, approval_type, amount, due_date'
            },
            {
                'name': 'payslip_ready',
                'content': 'Your payslip for {pay_period} is ready. Net pay: KES {net_pay}',
                'category': 'payroll',
                'description': 'Payslip ready SMS',
                'available_variables': 'employee_name, pay_period, net_pay'
            }
        ]

        for template_data in sms_templates:
            template, created = SMSTemplate.objects.get_or_create(
                name=template_data['name'],
                defaults=template_data
            )
            if created:
                self.stdout.write(f'✓ Created SMS template: {template_data["name"]}')

        # Push Templates
        push_templates = [
            {
                'name': 'welcome_push',
                'title': 'Welcome to Bengo ERP!',
                'body': 'Your account is ready. Start exploring the system.',
                'category': 'user_management',
                'description': 'Welcome push notification'
            },
            {
                'name': 'approval_required_push',
                'title': 'Approval Required',
                'body': '{approval_type} approval pending for {amount}',
                'category': 'approvals',
                'description': 'Approval required push notification'
            },
            {
                'name': 'payslip_ready_push',
                'title': 'Payslip Ready',
                'body': 'Your payslip for {pay_period} is ready for review',
                'category': 'payroll',
                'description': 'Payslip ready push notification'
            }
        ]

        for template_data in push_templates:
            template, created = PushTemplate.objects.get_or_create(
                name=template_data['name'],
                defaults=template_data
            )
            if created:
                self.stdout.write(f'✓ Created push template: {template_data["name"]}')

        self.stdout.write(
            self.style.SUCCESS('All default templates created successfully!')
        )
