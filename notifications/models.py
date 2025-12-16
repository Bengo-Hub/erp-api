"""
Centralized Notifications App Models
Consolidates all notification functionality from core and integrations apps
"""
from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from decimal import Decimal
from datetime import time as _time

User = get_user_model()

# Integration Type Choices
INTEGRATION_TYPES = [
    ('EMAIL', 'Email Integration'),
    ('SMS', 'SMS Integration'),
    ('PUSH', 'Push Notification Integration'),
    ('IN_APP', 'In-App Notification Integration'),
]

# SMS Provider Choices
SMS_PROVIDERS = [
    ('TWILIO', 'Twilio'),
    ('AFRICASTALKING', 'Africa\'s Talking'),
    ('NEXMO', 'Nexmo/Vonage'),
    ('AWS_SNS', 'AWS SNS'),
    ('SMS_GATEWAY', 'SMS Gateway'),
]

# Email Provider Choices
EMAIL_PROVIDERS = [
    ('SMTP', 'SMTP'),
    ('SENDGRID', 'SendGrid'),
    ('MAILGUN', 'Mailgun'),
    ('AMAZON_SES', 'Amazon SES'),
    ('MANDRILL', 'Mandrill'),
]

# Push Notification Providers
PUSH_PROVIDERS = [
    ('WEB_PUSH', 'Web Push'),
    ('FIREBASE', 'Firebase Cloud Messaging'),
    ('APNS', 'Apple Push Notification Service'),
    ('FCM', 'Firebase Cloud Messaging'),
]

# Notification Status Choices
NOTIFICATION_STATUS = [
    ('PENDING', 'Pending'),
    ('SENT', 'Sent'),
    ('DELIVERED', 'Delivered'),
    ('FAILED', 'Failed'),
    ('BOUNCED', 'Bounced'),
    ('OPENED', 'Opened'),
    ('CLICKED', 'Clicked'),
]

# Notification Types
NOTIFICATION_TYPES = [
    ('SYSTEM', 'System Notification'),
    ('ORDER', 'Order Notification'),
    ('PAYMENT', 'Payment Notification'),
    ('PAYROLL', 'Payroll Notification'),
    ('APPROVAL', 'Approval Notification'),
    ('SECURITY', 'Security Notification'),
    ('MARKETING', 'Marketing Notification'),
    ('REMINDER', 'Reminder Notification'),
]


class BaseModel(models.Model):
    """Base model with common fields"""
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class NotificationIntegration(BaseModel):
    """Base model for all notification integrations"""
    name = models.CharField(max_length=100, unique=True)
    integration_type = models.CharField(max_length=20, choices=INTEGRATION_TYPES)
    provider = models.CharField(max_length=50, blank=True, null=True)
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    priority = models.IntegerField(default=100, help_text="Higher number = higher priority")
    
    def __str__(self):
        return f"{self.name} ({self.integration_type})"
    
    def save(self, *args, **kwargs):
        # If this integration is set as default, unset any other defaults of the same type
        if self.is_default:
            NotificationIntegration.objects.filter(
                integration_type=self.integration_type, 
                is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)
    
    class Meta:
        verbose_name = "Notification Integration"
        verbose_name_plural = "Notification Integrations"
        ordering = ['integration_type', '-is_default', 'priority', 'name']


class EmailConfiguration(BaseModel):
    """Email configuration settings"""
    integration = models.OneToOneField(
        NotificationIntegration, 
        on_delete=models.CASCADE, 
        related_name='email_config',
        limit_choices_to={'integration_type': 'EMAIL'}
    )
    provider = models.CharField(max_length=20, choices=EMAIL_PROVIDERS, default='SMTP')
    from_email = models.EmailField(max_length=100, default="gadmin@masterserpace.co.ke")
    from_name = models.CharField(max_length=100, default="Masters ERP")
    
    # SMTP Settings
    smtp_host = models.CharField(max_length=100, default="smtppro.zoho.com")
    smtp_port = models.IntegerField(default=587)
    smtp_username = models.CharField(max_length=100, blank=True, null=True)
    smtp_password = models.CharField(max_length=255, blank=True, null=True)
    use_tls = models.BooleanField(default=True)
    use_ssl = models.BooleanField(default=False)
    fail_silently = models.BooleanField(default=False)
    timeout = models.IntegerField(default=60)
    
    # API Settings (for SendGrid, Mailgun, etc.)
    api_key = models.CharField(max_length=1500, blank=True, null=True)
    api_secret = models.CharField(max_length=1500, blank=True, null=True)
    api_url = models.URLField(blank=True, null=True)
    
    def save(self, *args, **kwargs):
        """Auto-encrypt sensitive fields before saving"""
        from integrations.utils import Crypto
        
        # Encrypt passwords/keys if not already encrypted
        if self.smtp_password and "gAAAAA" not in str(self.smtp_password):
            self.smtp_password = Crypto(self.smtp_password, 'encrypt').encrypt()
        if self.api_key and "gAAAAA" not in str(self.api_key):
            self.api_key = Crypto(self.api_key, 'encrypt').encrypt()
        if self.api_secret and "gAAAAA" not in str(self.api_secret):
            self.api_secret = Crypto(self.api_secret, 'encrypt').encrypt()
        
        super().save(*args, **kwargs)
    
    def get_decrypted_smtp_password(self):
        """
        Get decrypted SMTP password for secure use in email sending.
        
        Returns:
            str: The decrypted password, or empty string if not available
        """
        if not self.smtp_password:
            return ""
        
        try:
            from integrations.utils import Crypto
            # Check if the password is encrypted (starts with Fernet token prefix)
            if self.smtp_password.startswith("gAAAAA"):
                crypto = Crypto(self.smtp_password, 'decrypt')
                decrypted = crypto.decrypt()
                return decrypted if not decrypted.startswith("Error") else ""
            else:
                # Password is not encrypted, return as-is
                return self.smtp_password
        except Exception as e:
            import logging
            logger = logging.getLogger('notifications')
            logger.error(f"Failed to decrypt SMTP password: {str(e)}")
            return ""
    
    def get_decrypted_api_key(self):
        """
        Get decrypted API key for secure use.
        
        Returns:
            str: The decrypted API key, or empty string if not available
        """
        if not self.api_key:
            return ""
        
        try:
            from integrations.utils import Crypto
            if self.api_key.startswith("gAAAAA"):
                crypto = Crypto(self.api_key, 'decrypt')
                decrypted = crypto.decrypt()
                return decrypted if not decrypted.startswith("Error") else ""
            else:
                return self.api_key
        except Exception as e:
            import logging
            logger = logging.getLogger('notifications')
            logger.error(f"Failed to decrypt API key: {str(e)}")
            return ""
    
    def get_decrypted_api_secret(self):
        """
        Get decrypted API secret for secure use.
        
        Returns:
            str: The decrypted API secret, or empty string if not available
        """
        if not self.api_secret:
            return ""
        
        try:
            from integrations.utils import Crypto
            if self.api_secret.startswith("gAAAAA"):
                crypto = Crypto(self.api_secret, 'decrypt')
                decrypted = crypto.decrypt()
                return decrypted if not decrypted.startswith("Error") else ""
            else:
                return self.api_secret
        except Exception as e:
            import logging
            logger = logging.getLogger('notifications')
            logger.error(f"Failed to decrypt API secret: {str(e)}")
            return ""
    
    def __str__(self):
        return f"{self.integration.name} - {self.from_email}"
    
    class Meta:
        verbose_name = "Email Configuration"
        verbose_name_plural = "Email Configurations"


class SMSConfiguration(BaseModel):
    """SMS provider configuration"""
    integration = models.OneToOneField(
        NotificationIntegration, 
        on_delete=models.CASCADE, 
        related_name='sms_config',
        limit_choices_to={'integration_type': 'SMS'}
    )
    provider = models.CharField(max_length=20, choices=SMS_PROVIDERS)
    
    # Twilio Settings
    account_sid = models.CharField(max_length=1500, blank=True, null=True, help_text="For Twilio")
    auth_token = models.CharField(max_length=1500, blank=True, null=True, help_text="For Twilio/AfricasTalking")
    from_number = models.CharField(max_length=20, blank=True, null=True, help_text="For Twilio")
    
    # AfricasTalking Settings
    api_key = models.CharField(max_length=1500, blank=True, null=True, help_text="For AfricasTalking/Nexmo")
    api_username = models.CharField(max_length=100, blank=True, null=True, help_text="For AfricasTalking")
    
    # AWS SNS Settings
    aws_access_key = models.CharField(max_length=1500, blank=True, null=True, help_text="For AWS SNS")
    aws_secret_key = models.CharField(max_length=1500, blank=True, null=True, help_text="For AWS SNS")
    aws_region = models.CharField(max_length=50, default="us-east-1", help_text="For AWS SNS")
    
    def save(self, *args, **kwargs):
        """Auto-encrypt sensitive fields before saving"""
        from integrations.utils import Crypto
        
        # Encrypt API keys/tokens if not already encrypted
        if self.api_key and "gAAAAA" not in str(self.api_key):
            self.api_key = Crypto(self.api_key, 'encrypt').encrypt()
        if self.auth_token and "gAAAAA" not in str(self.auth_token):
            self.auth_token = Crypto(self.auth_token, 'encrypt').encrypt()
        if self.account_sid and "gAAAAA" not in str(self.account_sid):
            self.account_sid = Crypto(self.account_sid, 'encrypt').encrypt()
        if self.aws_access_key and "gAAAAA" not in str(self.aws_access_key):
            self.aws_access_key = Crypto(self.aws_access_key, 'encrypt').encrypt()
        if self.aws_secret_key and "gAAAAA" not in str(self.aws_secret_key):
            self.aws_secret_key = Crypto(self.aws_secret_key, 'encrypt').encrypt()
        
        super().save(*args, **kwargs)
    
    def get_decrypted_account_sid(self):
        """Get decrypted Twilio account SID"""
        if not self.account_sid:
            return ""
        try:
            from integrations.utils import Crypto
            if self.account_sid.startswith("gAAAAA"):
                crypto = Crypto(self.account_sid, 'decrypt')
                decrypted = crypto.decrypt()
                return decrypted if not decrypted.startswith("Error") else ""
            return self.account_sid
        except Exception as e:
            import logging
            logging.getLogger('notifications').error(f"Failed to decrypt account SID: {str(e)}")
            return ""
    
    def get_decrypted_auth_token(self):
        """Get decrypted auth token"""
        if not self.auth_token:
            return ""
        try:
            from integrations.utils import Crypto
            if self.auth_token.startswith("gAAAAA"):
                crypto = Crypto(self.auth_token, 'decrypt')
                decrypted = crypto.decrypt()
                return decrypted if not decrypted.startswith("Error") else ""
            return self.auth_token
        except Exception as e:
            import logging
            logging.getLogger('notifications').error(f"Failed to decrypt auth token: {str(e)}")
            return ""
    
    def get_decrypted_api_key(self):
        """Get decrypted API key"""
        if not self.api_key:
            return ""
        try:
            from integrations.utils import Crypto
            if self.api_key.startswith("gAAAAA"):
                crypto = Crypto(self.api_key, 'decrypt')
                decrypted = crypto.decrypt()
                return decrypted if not decrypted.startswith("Error") else ""
            return self.api_key
        except Exception as e:
            import logging
            logging.getLogger('notifications').error(f"Failed to decrypt API key: {str(e)}")
            return ""
    
    def get_decrypted_aws_access_key(self):
        """Get decrypted AWS access key"""
        if not self.aws_access_key:
            return ""
        try:
            from integrations.utils import Crypto
            if self.aws_access_key.startswith("gAAAAA"):
                crypto = Crypto(self.aws_access_key, 'decrypt')
                decrypted = crypto.decrypt()
                return decrypted if not decrypted.startswith("Error") else ""
            return self.aws_access_key
        except Exception as e:
            import logging
            logging.getLogger('notifications').error(f"Failed to decrypt AWS access key: {str(e)}")
            return ""
    
    def get_decrypted_aws_secret_key(self):
        """Get decrypted AWS secret key"""
        if not self.aws_secret_key:
            return ""
        try:
            from integrations.utils import Crypto
            if self.aws_secret_key.startswith("gAAAAA"):
                crypto = Crypto(self.aws_secret_key, 'decrypt')
                decrypted = crypto.decrypt()
                return decrypted if not decrypted.startswith("Error") else ""
            return self.aws_secret_key
        except Exception as e:
            import logging
            logging.getLogger('notifications').error(f"Failed to decrypt AWS secret key: {str(e)}")
            return ""
    
    def __str__(self):
        return f"{self.integration.name} - {self.provider}"
    
    class Meta:
        verbose_name = "SMS Configuration"
        verbose_name_plural = "SMS Configurations"


class PushConfiguration(BaseModel):
    """Push notification configuration"""
    integration = models.OneToOneField(
        NotificationIntegration, 
        on_delete=models.CASCADE, 
        related_name='push_config',
        limit_choices_to={'integration_type': 'PUSH'}
    )
    provider = models.CharField(max_length=20, choices=PUSH_PROVIDERS)
    
    # Firebase Settings
    firebase_server_key = models.CharField(max_length=500, blank=True, null=True, help_text="For Firebase")
    firebase_project_id = models.CharField(max_length=100, blank=True, null=True, help_text="For Firebase")
    
    # APNS Settings
    apns_certificate = models.TextField(blank=True, null=True, help_text="For APNS")
    apns_private_key = models.TextField(blank=True, null=True, help_text="For APNS")
    apns_team_id = models.CharField(max_length=100, blank=True, null=True, help_text="For APNS")
    apns_key_id = models.CharField(max_length=100, blank=True, null=True, help_text="For APNS")
    
    def __str__(self):
        return f"{self.integration.name} - {self.provider}"
    
    class Meta:
        verbose_name = "Push Configuration"
        verbose_name_plural = "Push Configurations"


class EmailTemplate(BaseModel):
    """Email templates for various system notifications"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    subject = models.CharField(max_length=255)
    body_html = models.TextField()
    body_text = models.TextField(blank=True, null=True)
    category = models.CharField(max_length=50, default="general")
    is_active = models.BooleanField(default=True)
    
    # Template variables documentation
    available_variables = models.TextField(
        blank=True, 
        null=True, 
        help_text="Documentation of available template variables (e.g., {username}, {first_name}, {last_name})"
    )
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "Email Template"
        verbose_name_plural = "Email Templates"
        ordering = ['category', 'name']


class SMSTemplate(BaseModel):
    """Templates for SMS notifications"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    content = models.TextField(help_text="Use {variable} for dynamic content")
    category = models.CharField(max_length=50, default="general")
    is_active = models.BooleanField(default=True)
    
    # Template variables documentation
    available_variables = models.TextField(
        blank=True, 
        null=True, 
        help_text="Documentation of available template variables"
    )
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "SMS Template"
        verbose_name_plural = "SMS Templates"
        ordering = ['category', 'name']


class PushTemplate(BaseModel):
    """Templates for push notifications"""
    name = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True, null=True)
    title = models.CharField(max_length=255)
    body = models.TextField()
    category = models.CharField(max_length=50, default="general")
    is_active = models.BooleanField(default=True)
    
    # Additional push notification fields
    icon = models.CharField(max_length=255, blank=True, null=True)
    sound = models.CharField(max_length=255, blank=True, null=True)
    badge = models.IntegerField(blank=True, null=True)
    
    def __str__(self):
        return self.name
    
    class Meta:
        verbose_name = "Push Template"
        verbose_name_plural = "Push Templates"
        ordering = ['category', 'name']


class EmailLog(BaseModel):
    """Logs for all emails sent through the system"""
    integration = models.ForeignKey(NotificationIntegration, on_delete=models.SET_NULL, null=True, blank=True)
    sender = models.EmailField(max_length=100)
    recipients = models.TextField()  # Stored as comma-separated list
    cc = models.TextField(blank=True, null=True)  # Stored as comma-separated list
    bcc = models.TextField(blank=True, null=True)  # Stored as comma-separated list
    subject = models.CharField(max_length=255)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=NOTIFICATION_STATUS, default='PENDING')
    error_message = models.TextField(blank=True, null=True)
    template = models.ForeignKey(EmailTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    clicked_at = models.DateTimeField(null=True, blank=True)
    
    # Tracking data
    message_id = models.CharField(max_length=255, blank=True, null=True)
    tracking_id = models.CharField(max_length=255, blank=True, null=True)
    
    def __str__(self):
        return f"{self.subject} - {self.status} - {self.sent_at.strftime('%Y-%m-%d %H:%M')}"
    
    class Meta:
        verbose_name = "Email Log"
        verbose_name_plural = "Email Logs"
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['sent_at']),
            models.Index(fields=['template']),
        ]


class SMSLog(BaseModel):
    """Logs for all SMS messages sent through the system"""
    integration = models.ForeignKey(NotificationIntegration, on_delete=models.SET_NULL, null=True, blank=True)
    sender = models.CharField(max_length=20, blank=True, null=True)
    recipient = models.CharField(max_length=20)
    message = models.TextField()
    status = models.CharField(max_length=20, choices=NOTIFICATION_STATUS, default='PENDING')
    error_message = models.TextField(blank=True, null=True)
    provider = models.CharField(max_length=20, choices=SMS_PROVIDERS)
    template = models.ForeignKey(SMSTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    
    # Tracking data
    message_id = models.CharField(max_length=100, blank=True, null=True)
    tracking_id = models.CharField(max_length=255, blank=True, null=True)
    
    def __str__(self):
        return f"{self.recipient} - {self.status} - {self.sent_at.strftime('%Y-%m-%d %H:%M')}"
    
    class Meta:
        verbose_name = "SMS Log"
        verbose_name_plural = "SMS Logs"
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['sent_at']),
            models.Index(fields=['provider']),
        ]


class PushLog(BaseModel):
    """Logs for all push notifications sent through the system"""
    integration = models.ForeignKey(NotificationIntegration, on_delete=models.SET_NULL, null=True, blank=True)
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='push_logs')
    title = models.CharField(max_length=255)
    body = models.TextField()
    status = models.CharField(max_length=20, choices=NOTIFICATION_STATUS, default='PENDING')
    error_message = models.TextField(blank=True, null=True)
    template = models.ForeignKey(PushTemplate, on_delete=models.SET_NULL, null=True, blank=True)
    sent_at = models.DateTimeField(auto_now_add=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    opened_at = models.DateTimeField(null=True, blank=True)
    
    # Push notification specific fields
    device_token = models.CharField(max_length=500, blank=True, null=True)
    platform = models.CharField(max_length=20, blank=True, null=True)  # ios, android, web
    
    # Tracking data
    message_id = models.CharField(max_length=255, blank=True, null=True)
    tracking_id = models.CharField(max_length=255, blank=True, null=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.title} - {self.status}"
    
    class Meta:
        verbose_name = "Push Log"
        verbose_name_plural = "Push Logs"
        ordering = ['-sent_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['sent_at']),
            models.Index(fields=['user']),
        ]


class InAppNotification(BaseModel):
    """In-app notifications for users"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='in_app_notifications')
    title = models.CharField(max_length=255)
    message = models.TextField()
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    is_read = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    
    # Action fields
    action_url = models.URLField(blank=True, null=True)
    action_text = models.CharField(max_length=100, blank=True, null=True)
    
    # Additional data
    data = models.JSONField(default=dict, blank=True)
    image_url = models.URLField(blank=True, null=True)
    
    # Priority and expiration
    priority = models.IntegerField(default=1, help_text="1=Low, 2=Normal, 3=High, 4=Urgent")
    expires_at = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.user.username} - {self.title}"
    
    class Meta:
        verbose_name = "In-App Notification"
        verbose_name_plural = "In-App Notifications"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'is_read']),
            models.Index(fields=['notification_type']),
            models.Index(fields=['created_at']),
        ]


class UserNotificationPreferences(BaseModel):
    """User-specific notification preferences"""
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='notifications_preferences')
    
    # Email preferences
    email_notifications_enabled = models.BooleanField(default=True)
    email_order_updates = models.BooleanField(default=True)
    email_payment_alerts = models.BooleanField(default=True)
    email_payroll_updates = models.BooleanField(default=True)
    email_approval_requests = models.BooleanField(default=True)
    email_security_alerts = models.BooleanField(default=True)
    email_marketing = models.BooleanField(default=False)
    email_frequency = models.CharField(max_length=20, choices=[
        ('immediate', 'Immediate'),
        ('daily', 'Daily Digest'),
        ('weekly', 'Weekly Digest'),
        ('monthly', 'Monthly Digest'),
    ], default='immediate')
    
    # SMS preferences
    sms_notifications_enabled = models.BooleanField(default=True)
    sms_order_updates = models.BooleanField(default=True)
    sms_payment_alerts = models.BooleanField(default=True)
    sms_payroll_updates = models.BooleanField(default=True)
    sms_security_alerts = models.BooleanField(default=True)
    sms_marketing = models.BooleanField(default=False)
    
    # Push notification preferences
    push_notifications_enabled = models.BooleanField(default=True)
    push_order_updates = models.BooleanField(default=True)
    push_payment_alerts = models.BooleanField(default=True)
    push_payroll_updates = models.BooleanField(default=True)
    push_approval_requests = models.BooleanField(default=True)
    push_security_alerts = models.BooleanField(default=True)
    push_marketing = models.BooleanField(default=False)
    
    # In-app notification preferences
    in_app_notifications_enabled = models.BooleanField(default=True)
    in_app_order_updates = models.BooleanField(default=True)
    in_app_payment_alerts = models.BooleanField(default=True)
    in_app_payroll_updates = models.BooleanField(default=True)
    in_app_approval_requests = models.BooleanField(default=True)
    in_app_security_alerts = models.BooleanField(default=True)
    in_app_marketing = models.BooleanField(default=False)
    
    # Quiet hours
    quiet_hours_enabled = models.BooleanField(default=False)
    quiet_hours_start = models.TimeField(default=_time(22, 0, 0))
    quiet_hours_end = models.TimeField(default=_time(8, 0, 0))
    
    # Language and timezone
    preferred_language = models.CharField(max_length=10, default='en')
    timezone = models.CharField(max_length=50, default='Africa/Nairobi')
    
    def __str__(self):
        return f"Notification Preferences - {self.user.username}"
    
    class Meta:
        verbose_name = "User Notification Preferences"
        verbose_name_plural = "User Notification Preferences"

class BounceRecord(BaseModel):
    """Records for bounced emails and failed SMS"""
    BOUNCE_TYPE_CHOICES = [
        ('hard', 'Hard Bounce'),
        ('soft', 'Soft Bounce'),
        ('blocked', 'Blocked'),
        ('spam', 'Spam Report'),
        ('unsubscribed', 'Unsubscribed'),
        ('invalid', 'Invalid Address'),
        ('quota_exceeded', 'Quota Exceeded'),
        ('temporary', 'Temporary Failure'),
    ]
    
    COMMUNICATION_TYPE_CHOICES = [
        ('email', 'Email'),
        ('sms', 'SMS'),
        ('push', 'Push Notification'),
    ]
    
    communication_type = models.CharField(max_length=10, choices=COMMUNICATION_TYPE_CHOICES)
    recipient = models.CharField(max_length=255)  # email or phone number
    bounce_type = models.CharField(max_length=20, choices=BOUNCE_TYPE_CHOICES)
    error_message = models.TextField(blank=True, null=True)
    provider_message = models.TextField(blank=True, null=True)
    
    # Related records
    email_log = models.ForeignKey(EmailLog, on_delete=models.SET_NULL, null=True, blank=True)
    sms_log = models.ForeignKey(SMSLog, on_delete=models.SET_NULL, null=True, blank=True)
    push_log = models.ForeignKey(PushLog, on_delete=models.SET_NULL, null=True, blank=True)
    
    # Bounce handling
    is_suppressed = models.BooleanField(default=False)
    suppression_reason = models.CharField(max_length=100, blank=True, null=True)
    suppression_date = models.DateTimeField(null=True, blank=True)
    
    # Retry information
    retry_count = models.IntegerField(default=0)
    last_retry_date = models.DateTimeField(null=True, blank=True)
    next_retry_date = models.DateTimeField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.communication_type} Bounce - {self.recipient} ({self.bounce_type})"
    
    class Meta:
        verbose_name = "Bounce Record"
        verbose_name_plural = "Bounce Records"
        indexes = [
            models.Index(fields=['communication_type', 'recipient']),
            models.Index(fields=['bounce_type']),
            models.Index(fields=['is_suppressed']),
            models.Index(fields=['created_at']),
        ]


class SpamPreventionRule(BaseModel):
    """Rules for spam prevention and content filtering"""
    RULE_TYPE_CHOICES = [
        ('content_filter', 'Content Filter'),
        ('rate_limit', 'Rate Limiting'),
        ('blacklist', 'Blacklist'),
        ('whitelist', 'Whitelist'),
        ('keyword_filter', 'Keyword Filter'),
    ]
    
    name = models.CharField(max_length=100)
    rule_type = models.CharField(max_length=20, choices=RULE_TYPE_CHOICES)
    description = models.TextField(blank=True, null=True)
    
    # Rule configuration
    is_active = models.BooleanField(default=True)
    priority = models.IntegerField(default=100)  # Higher number = higher priority
    
    # Content filter rules
    keywords = models.JSONField(default=list, blank=True)  # List of keywords to filter
    patterns = models.JSONField(default=list, blank=True)  # List of regex patterns
    
    # Rate limiting rules
    rate_limit_count = models.IntegerField(default=100)
    rate_limit_period = models.IntegerField(default=3600)  # in seconds
    rate_limit_window = models.CharField(max_length=20, choices=[
        ('per_minute', 'Per Minute'),
        ('per_hour', 'Per Hour'),
        ('per_day', 'Per Day'),
    ], default='per_hour')
    
    # Blacklist/Whitelist
    addresses = models.JSONField(default=list, blank=True)  # List of email/phone addresses
    domains = models.JSONField(default=list, blank=True)  # List of domains
    
    # Actions
    action = models.CharField(max_length=20, choices=[
        ('block', 'Block'),
        ('flag', 'Flag for Review'),
        ('quarantine', 'Quarantine'),
        ('allow', 'Allow'),
        ('rate_limit', 'Rate Limit'),
    ], default='block')
    
    def __str__(self):
        return f"{self.name} ({self.rule_type})"
    
    class Meta:
        verbose_name = "Spam Prevention Rule"
        verbose_name_plural = "Spam Prevention Rules"
        ordering = ['-priority', 'name']


