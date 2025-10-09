from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()


class ErrorSeverity(models.TextChoices):
    LOW = 'low', 'Low'
    MEDIUM = 'medium', 'Medium'
    HIGH = 'high', 'High'
    CRITICAL = 'critical', 'Critical'


class ErrorStatus(models.TextChoices):
    OPEN = 'open', 'Open'
    IN_PROGRESS = 'in_progress', 'In Progress'
    RESOLVED = 'resolved', 'Resolved'
    CLOSED = 'closed', 'Closed'
    IGNORED = 'ignored', 'Ignored'


class ErrorCategory(models.TextChoices):
    VALIDATION = 'validation', 'Validation Error'
    AUTHENTICATION = 'authentication', 'Authentication Error'
    AUTHORIZATION = 'authorization', 'Authorization Error'
    DATABASE = 'database', 'Database Error'
    NETWORK = 'network', 'Network Error'
    INTEGRATION = 'integration', 'Integration Error'
    BUSINESS_LOGIC = 'business_logic', 'Business Logic Error'
    SYSTEM = 'system', 'System Error'
    PERFORMANCE = 'performance', 'Performance Error'
    SECURITY = 'security', 'Security Error'


class Error(models.Model):
    """
    Centralized error tracking for all ERP modules
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    error_id = models.CharField(max_length=255, unique=True, help_text="Unique error identifier")
    
    # Error details
    title = models.CharField(max_length=255)
    description = models.TextField()
    category = models.CharField(max_length=50, choices=ErrorCategory.choices)
    severity = models.CharField(max_length=20, choices=ErrorSeverity.choices, default=ErrorSeverity.MEDIUM)
    status = models.CharField(max_length=20, choices=ErrorStatus.choices, default=ErrorStatus.OPEN)
    
    # Context
    module = models.CharField(max_length=50, help_text="ERP module where error occurred")
    function_name = models.CharField(max_length=255, blank=True, null=True)
    user_agent = models.TextField(blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    
    # User and session
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='errors')
    session_id = models.CharField(max_length=255, blank=True, null=True)
    
    # Error data
    error_message = models.TextField()
    error_traceback = models.TextField(blank=True, null=True)
    error_data = models.JSONField(default=dict, blank=True)
    
    # Request context
    request_method = models.CharField(max_length=10, blank=True, null=True)
    request_url = models.URLField(blank=True, null=True)
    request_data = models.JSONField(default=dict, blank=True)
    
    # Resolution
    resolved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='resolved_errors')
    resolved_at = models.DateTimeField(blank=True, null=True)
    resolution_notes = models.TextField(blank=True, null=True)
    
    # Timing
    occurred_at = models.DateTimeField(auto_now_add=True)
    last_occurred = models.DateTimeField(auto_now=True)
    occurrence_count = models.PositiveIntegerField(default=1)
    
    # Metadata
    tags = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    
    class Meta:
        ordering = ['-occurred_at']
        indexes = [
            models.Index(fields=['error_id']),
            models.Index(fields=['status']),
            models.Index(fields=['severity']),
            models.Index(fields=['category']),
            models.Index(fields=['module']),
            models.Index(fields=['user']),
            models.Index(fields=['occurred_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_severity_display()})"

    @property
    def is_resolved(self):
        return self.status in [ErrorStatus.RESOLVED, ErrorStatus.CLOSED]

    @property
    def is_critical(self):
        return self.severity == ErrorSeverity.CRITICAL

    def increment_occurrence(self):
        """Increment occurrence count and update last occurred time"""
        self.occurrence_count += 1
        self.last_occurred = timezone.now()
        self.save(update_fields=['occurrence_count', 'last_occurred'])

    def resolve(self, resolved_by, notes=None):
        """Mark error as resolved"""
        self.status = ErrorStatus.RESOLVED
        self.resolved_by = resolved_by
        self.resolved_at = timezone.now()
        if notes:
            self.resolution_notes = notes
        self.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_notes'])

    def close(self, closed_by, notes=None):
        """Mark error as closed"""
        self.status = ErrorStatus.CLOSED
        self.resolved_by = closed_by
        self.resolved_at = timezone.now()
        if notes:
            self.resolution_notes = notes
        self.save(update_fields=['status', 'resolved_by', 'resolved_at', 'resolution_notes'])


class ErrorLog(models.Model):
    """
    Detailed error logs for debugging
    """
    error = models.ForeignKey(Error, on_delete=models.CASCADE, related_name='logs')
    timestamp = models.DateTimeField(auto_now_add=True)
    level = models.CharField(max_length=20, choices=[
        ('debug', 'Debug'),
        ('info', 'Info'),
        ('warning', 'Warning'),
        ('error', 'Error'),
        ('critical', 'Critical'),
    ])
    message = models.TextField()
    data = models.JSONField(default=dict, blank=True)
    user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['error', 'timestamp']),
            models.Index(fields=['level']),
        ]

    def __str__(self):
        return f"{self.error.title} - {self.get_level_display()} - {self.timestamp}"


class ErrorPattern(models.Model):
    """
    Error patterns for automatic error classification
    """
    name = models.CharField(max_length=255, unique=True)
    pattern = models.TextField(help_text="Regex pattern to match error messages")
    category = models.CharField(max_length=50, choices=ErrorCategory.choices)
    severity = models.CharField(max_length=20, choices=ErrorSeverity.choices)
    module = models.CharField(max_length=50, blank=True, null=True)
    auto_resolve = models.BooleanField(default=False)
    resolution_notes = models.TextField(blank=True, null=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name