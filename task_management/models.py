from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
import uuid

User = get_user_model()


class TaskStatus(models.TextChoices):
    PENDING = 'pending', 'Pending'
    RUNNING = 'running', 'Running'
    COMPLETED = 'completed', 'Completed'
    FAILED = 'failed', 'Failed'
    CANCELLED = 'cancelled', 'Cancelled'


class TaskType(models.TextChoices):
    PAYROLL_PROCESSING = 'payroll_processing', 'Payroll Processing'
    PAYROLL_RERUN = 'payroll_rerun', 'Payroll Rerun'
    EMAIL_DISTRIBUTION = 'email_distribution', 'Email Distribution'
    VOUCHER_GENERATION = 'voucher_generation', 'Voucher Generation'
    REPORT_GENERATION = 'report_generation', 'Report Generation'
    DATA_IMPORT = 'data_import', 'Data Import'
    DATA_EXPORT = 'data_export', 'Data Export'
    SYSTEM_BACKUP = 'system_backup', 'System Backup'
    CACHE_CLEAR = 'cache_clear', 'Cache Clear'
    SYSTEM_MAINTENANCE = 'system_maintenance', 'System Maintenance'
    CUSTOM = 'custom', 'Custom'


class TaskPriority(models.TextChoices):
    LOW = 'low', 'Low'
    NORMAL = 'normal', 'Normal'
    HIGH = 'high', 'High'
    CRITICAL = 'critical', 'Critical'


class Task(models.Model):
    """
    Centralized task management model for all ERP modules
    """
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task_id = models.CharField(max_length=255, unique=True, help_text="Celery task ID")
    task_type = models.CharField(max_length=50, choices=TaskType.choices)
    status = models.CharField(max_length=20, choices=TaskStatus.choices, default=TaskStatus.PENDING)
    priority = models.CharField(max_length=20, choices=TaskPriority.choices, default=TaskPriority.NORMAL)
    
    # Task details
    title = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    module = models.CharField(max_length=50, help_text="ERP module (payroll, inventory, etc.)")
    
    # User and context
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_tasks')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_tasks')
    
    # Progress tracking
    progress = models.IntegerField(default=0, help_text="Progress percentage (0-100)")
    total_items = models.IntegerField(default=0, help_text="Total items to process")
    processed_items = models.IntegerField(default=0, help_text="Items processed so far")
    
    # Timing
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    estimated_duration = models.DurationField(null=True, blank=True)
    
    # Task data and results
    input_data = models.JSONField(default=dict, blank=True)
    output_data = models.JSONField(default=dict, blank=True)
    error_message = models.TextField(blank=True, null=True)
    error_traceback = models.TextField(blank=True, null=True)
    
    # Metadata
    metadata = models.JSONField(default=dict, blank=True)
    tags = models.JSONField(default=list, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['task_id']),
            models.Index(fields=['status']),
            models.Index(fields=['task_type']),
            models.Index(fields=['module']),
            models.Index(fields=['created_by']),
            models.Index(fields=['created_at']),
        ]

    def __str__(self):
        return f"{self.title} ({self.get_status_display()})"

    @property
    def duration(self):
        """Calculate actual task duration"""
        if self.started_at and self.completed_at:
            return self.completed_at - self.started_at
        elif self.started_at:
            return timezone.now() - self.started_at
        return None

    @property
    def is_running(self):
        return self.status == TaskStatus.RUNNING

    @property
    def is_completed(self):
        return self.status == TaskStatus.COMPLETED

    @property
    def is_failed(self):
        return self.status == TaskStatus.FAILED

    def update_progress(self, processed_items=None, progress=None):
        """Update task progress"""
        if processed_items is not None:
            self.processed_items = processed_items
            if self.total_items > 0:
                self.progress = int((processed_items / self.total_items) * 100)
        
        if progress is not None:
            self.progress = min(100, max(0, progress))
        
        self.save(update_fields=['progress', 'processed_items'])

    def mark_started(self):
        """Mark task as started"""
        self.status = TaskStatus.RUNNING
        self.started_at = timezone.now()
        self.save(update_fields=['status', 'started_at'])

    def mark_completed(self, output_data=None):
        """Mark task as completed"""
        self.status = TaskStatus.COMPLETED
        self.completed_at = timezone.now()
        self.progress = 100
        if output_data:
            self.output_data = output_data
        self.save(update_fields=['status', 'completed_at', 'progress', 'output_data'])

    def mark_failed(self, error_message=None, error_traceback=None):
        """Mark task as failed"""
        self.status = TaskStatus.FAILED
        self.completed_at = timezone.now()
        if error_message:
            self.error_message = error_message
        if error_traceback:
            self.error_traceback = error_traceback
        self.save(update_fields=['status', 'completed_at', 'error_message', 'error_traceback'])


class TaskLog(models.Model):
    """
    Task execution logs for audit and debugging
    """
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name='logs')
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

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['task', 'timestamp']),
            models.Index(fields=['level']),
        ]

    def __str__(self):
        return f"{self.task.title} - {self.get_level_display()} - {self.timestamp}"


class TaskTemplate(models.Model):
    """
    Reusable task templates for common operations
    """
    name = models.CharField(max_length=255, unique=True)
    task_type = models.CharField(max_length=50, choices=TaskType.choices)
    module = models.CharField(max_length=50)
    title_template = models.CharField(max_length=255)
    description_template = models.TextField(blank=True)
    input_schema = models.JSONField(default=dict, help_text="JSON schema for input validation")
    default_priority = models.CharField(max_length=20, choices=TaskPriority.choices, default=TaskPriority.NORMAL)
    estimated_duration = models.DurationField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']

    def __str__(self):
        return self.name