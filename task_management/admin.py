"""
Admin interface for centralized task management
"""
from django.contrib import admin
from django.utils.html import format_html
from django.urls import reverse
from django.utils import timezone
from .models import Task, TaskLog, TaskTemplate


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'task_type', 'module', 'status', 'priority', 
        'progress_bar', 'created_by', 'created_at', 'duration_display'
    ]
    list_filter = [
        'status', 'task_type', 'module', 'priority', 'created_at'
    ]
    search_fields = ['title', 'description', 'task_id', 'module']
    readonly_fields = [
        'task_id', 'created_at', 'started_at', 'completed_at', 
        'duration_display', 'progress_bar'
    ]
    fieldsets = (
        ('Basic Information', {
            'fields': ('task_id', 'title', 'description', 'task_type', 'module')
        }),
        ('Status & Progress', {
            'fields': ('status', 'priority', 'progress_bar', 'total_items', 'processed_items')
        }),
        ('Users', {
            'fields': ('created_by', 'assigned_to')
        }),
        ('Timing', {
            'fields': ('created_at', 'started_at', 'completed_at', 'duration_display', 'estimated_duration')
        }),
        ('Data', {
            'fields': ('input_data', 'output_data', 'error_message', 'metadata', 'tags'),
            'classes': ('collapse',)
        }),
    )
    
    def progress_bar(self, obj):
        """Display progress as a progress bar"""
        if obj.progress is None:
            return "N/A"
        
        color = 'green' if obj.progress >= 80 else 'orange' if obj.progress >= 50 else 'red'
        return format_html(
            '<div style="width: 100px; background-color: #f0f0f0; border-radius: 3px;">'
            '<div style="width: {}%; background-color: {}; height: 20px; border-radius: 3px; '
            'display: flex; align-items: center; justify-content: center; color: white; font-size: 12px;">'
            '{}%</div></div>',
            obj.progress, color, obj.progress
        )
    progress_bar.short_description = 'Progress'
    
    def duration_display(self, obj):
        """Display task duration"""
        if obj.duration:
            total_seconds = obj.duration.total_seconds()
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            seconds = int(total_seconds % 60)
            
            if hours > 0:
                return f"{hours}h {minutes}m {seconds}s"
            elif minutes > 0:
                return f"{minutes}m {seconds}s"
            else:
                return f"{seconds}s"
        return "N/A"
    duration_display.short_description = 'Duration'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('created_by', 'assigned_to')


@admin.register(TaskLog)
class TaskLogAdmin(admin.ModelAdmin):
    list_display = ['task', 'timestamp', 'level', 'message_preview']
    list_filter = ['level', 'timestamp', 'task__module', 'task__task_type']
    search_fields = ['task__title', 'message', 'task__task_id']
    readonly_fields = ['task', 'timestamp', 'level', 'message', 'data']
    
    def message_preview(self, obj):
        """Display truncated message"""
        if len(obj.message) > 100:
            return obj.message[:100] + "..."
        return obj.message
    message_preview.short_description = 'Message'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('task')


@admin.register(TaskTemplate)
class TaskTemplateAdmin(admin.ModelAdmin):
    list_display = ['name', 'task_type', 'module', 'default_priority', 'is_active', 'created_at']
    list_filter = ['task_type', 'module', 'default_priority', 'is_active', 'created_at']
    search_fields = ['name', 'title_template', 'description_template']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'task_type', 'module', 'is_active')
        }),
        ('Templates', {
            'fields': ('title_template', 'description_template')
        }),
        ('Configuration', {
            'fields': ('input_schema', 'default_priority', 'estimated_duration')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )