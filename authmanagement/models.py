from django.contrib.auth.hashers import make_password
from django.dispatch import receiver
from django.db.models.signals import post_save
from django.db import models
from django.urls import reverse
from datetime import datetime
from django.contrib.auth.models import AbstractUser, BaseUserManager
from django.utils.text import slugify
from django.utils import timezone
from timezone_field import TimeZoneField
from tinymce.models import HTMLField
from django.core.validators import RegexValidator

from phonenumber_field.modelfields import PhoneNumberField
# Define the Kenyan phone number regex pattern
kenyan_phone_regex = r"^(?:\+?254|0)(?:\d{9}|\d{3}\s\d{3}\s\d{3}|\d{2}\s\d{3}\s\d{3})$"

# Create a RegexValidator instance using the regex pattern
kenyan_phone_validator = RegexValidator(
    regex=kenyan_phone_regex,
    message="Please enter a valid Kenyan phone number."
)

class CustomUserManager(BaseUserManager):
    def create_user(self, email, password=None, **extra_fields):
        if not email:
            raise ValueError('Email must be set')
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save()
        return user

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('is_active', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True.')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True.')
        
        return self.create_user(email, password, **extra_fields)

class CustomUser(AbstractUser):
    username = models.CharField(
        max_length=150, unique=True, blank=True, null=True)
    email = models.EmailField(unique=True,verbose_name="Official Email")
    first_name = models.CharField(max_length=30, blank=False)
    last_name = models.CharField(max_length=150, blank=False)
    middle_name = models.CharField(max_length=255, blank=True, null=True)
    phone = models.CharField(max_length=15,default='+254743793901',validators=[kenyan_phone_validator],blank=True,null=True)
    pic=models.ImageField(upload_to='userprofiles',blank=True,null=True)
    timezone = TimeZoneField(choices_display="WITH_GMT_OFFSET",use_pytz=True, default="Africa/Nairobi", blank=True, null=True)
    email_confirm_token=models.CharField(max_length=255,default='token')
    ip_address = models.CharField(max_length=100, default="192.168.0.1")
    device = models.CharField(max_length=100, default="Phone")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    # Password lifecycle fields
    password_changed_at = models.DateTimeField(blank=True, null=True)
    must_change_password = models.BooleanField(default=False)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ['first_name','last_name']
    objects = CustomUserManager()

    def save(self, *args, **kwargs):
        if not self.username:
            self.username = slugify(self.email.split('@')[0])
        super().save(*args, **kwargs)

    def __str__(self):
        return self.first_name + " " + self.last_name

    class Meta:
        indexes = [
            models.Index(fields=['email'], name='idx_user_email'),
            models.Index(fields=['username'], name='idx_user_username'),
            models.Index(fields=['first_name'], name='idx_user_first_name'),
            models.Index(fields=['last_name'], name='idx_user_last_name'),
            models.Index(fields=['is_active'], name='idx_user_active'),
            models.Index(fields=['is_staff'], name='idx_user_staff'),
            models.Index(fields=['created_at'], name='idx_user_created_at'),
        ]


class PasswordPolicy(models.Model):
    min_length = models.PositiveIntegerField(default=8)
    require_uppercase = models.BooleanField(default=True)
    require_lowercase = models.BooleanField(default=True)
    require_numbers = models.BooleanField(default=True)
    require_special_chars = models.BooleanField(default=True)
    password_expiry_days = models.PositiveIntegerField(default=90)
    # Enforcements
    require_password_change_on_first_login = models.BooleanField(default=True)
    enforce_password_expiry = models.BooleanField(default=True)
    max_login_attempts = models.PositiveIntegerField(default=5)
    lockout_duration_minutes = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Password Policy (Updated: {self.updated_at})"

    class Meta:
        indexes = [
            models.Index(fields=['created_at'], name='idx_password_policy_created_at'),
        ]


class Backup(models.Model):
    TYPE_CHOICES = [
        ('full', 'Full Backup'),
        ('incremental', 'Incremental Backup')
    ]
    
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('in_progress', 'In Progress'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ]

    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    path = models.CharField(max_length=255)
    size = models.BigIntegerField(help_text="Size in bytes")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    error_message = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.type} backup - {self.created_at}"

    class Meta:
        indexes = [
            models.Index(fields=['type'], name='idx_backup_type'),
            models.Index(fields=['status'], name='idx_backup_status'),
            models.Index(fields=['created_at'], name='idx_backup_created_at'),
        ]


class BackupConfig(models.Model):
    STORAGE_CHOICES = [
        ('local', 'Local Storage'),
        ('s3', 'Amazon S3')
    ]

    storage_type = models.CharField(max_length=10, choices=STORAGE_CHOICES, default='local')
    local_path = models.CharField(max_length=255, null=True, blank=True)
    s3_bucket = models.CharField(max_length=255, null=True, blank=True)
    s3_region = models.CharField(max_length=50, null=True, blank=True)
    s3_access_key = models.CharField(max_length=255, null=True, blank=True)
    s3_secret_key = models.CharField(max_length=255, null=True, blank=True)
    retention_days = models.PositiveIntegerField(default=30)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Backup Configuration ({self.storage_type})"

    class Meta:
        indexes = [
            models.Index(fields=['storage_type'], name='idx_backup_config_storage_type'),
        ]


class BackupSchedule(models.Model):
    FREQUENCY_CHOICES = [
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('custom', 'Custom')
    ]

    frequency = models.CharField(max_length=10, choices=FREQUENCY_CHOICES)
    cron_expression = models.CharField(max_length=100, null=True, blank=True)
    last_run = models.DateTimeField(null=True, blank=True)
    next_run = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Backup Schedule ({self.frequency})"

    class Meta:
        indexes = [
            models.Index(fields=['frequency'], name='idx_backup_schedule_frequency'),
            models.Index(fields=['is_active'], name='idx_backup_schedule_active'),
            models.Index(fields=['next_run'], name='idx_backup_schedule_next_run'),
        ]


class UserLog(models.Model):
    ACTION_CHOICES = [
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('password_change', 'Password Change'),
        ('password_reset', 'Password Reset'),
        ('profile_update', 'Profile Update'),
        ('role_change', 'Role Change'),
        ('permission_change', 'Permission Change')
    ]

    user = models.ForeignKey(CustomUser, on_delete=models.CASCADE)
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} - {self.action} - {self.created_at}"

    class Meta:
        indexes = [
            models.Index(fields=['user'], name='idx_user_log_user'),
            models.Index(fields=['action'], name='idx_user_log_action'),
            models.Index(fields=['created_at'], name='idx_user_log_created_at'),
        ]


class AccountRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ]

    email = models.EmailField()
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    phone = models.CharField(max_length=20)
    status = models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name} - {self.email}"

    class Meta:
        indexes = [
            models.Index(fields=['email'], name='idx_account_request_email'),
            models.Index(fields=['status'], name='idx_account_request_status'),
            models.Index(fields=['created_at'], name='idx_account_request_created_at'),
        ]


class UserPreferences(models.Model):
    """
    Store user-specific preferences including theme settings
    """
    user = models.OneToOneField(CustomUser, on_delete=models.CASCADE, related_name='preferences')
    theme_settings = models.JSONField(default=dict, blank=True, help_text="Theme configuration (preset, colors, menu mode, etc.)")
    notification_settings = models.JSONField(default=dict, blank=True, help_text="Notification preferences")
    dashboard_layout = models.JSONField(default=dict, blank=True, help_text="Dashboard widget layout")
    language = models.CharField(max_length=10, default='en', help_text="User interface language")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Preferences for {self.user.email}"

    class Meta:
        verbose_name = 'User Preferences'
        verbose_name_plural = 'User Preferences'
        indexes = [
            models.Index(fields=['user'], name='idx_user_preferences_user'),
        ]