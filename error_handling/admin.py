"""
Admin interface for centralized error handling
"""
from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from .models import Error, ErrorLog, ErrorPattern


@admin.register(Error)
class ErrorAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'module', 'category', 'severity', 'status', 
        'occurrence_count', 'user', 'occurred_at', 'is_resolved'
    ]
    list_filter = [
        'status', 'severity', 'category', 'module', 'occurred_at'
    ]
    search_fields = ['title', 'description', 'error_message', 'module']
    readonly_fields = [
        'error_id', 'occurred_at', 'last_occurred', 'occurrence_count',
        'is_resolved', 'is_critical'
    ]
    fieldsets = (
        ('Basic Information', {
            'fields': ('error_id', 'title', 'description', 'category', 'severity', 'status')
        }),
        ('Context', {
            'fields': ('module', 'function_name', 'user', 'session_id')
        }),
        ('Error Details', {
            'fields': ('error_message', 'error_traceback', 'error_data'),
            'classes': ('collapse',)
        }),
        ('Request Context', {
            'fields': ('request_method', 'request_url', 'request_data', 'ip_address', 'user_agent'),
            'classes': ('collapse',)
        }),
        ('Resolution', {
            'fields': ('resolved_by', 'resolved_at', 'resolution_notes')
        }),
        ('Timing', {
            'fields': ('occurred_at', 'last_occurred', 'occurrence_count')
        }),
        ('Metadata', {
            'fields': ('tags', 'metadata'),
            'classes': ('collapse',)
        }),
    )
    
    def is_resolved(self, obj):
        """Display resolved status"""
        if obj.is_resolved:
            return format_html('<span style="color: green;">✓ Resolved</span>')
        else:
            return format_html('<span style="color: red;">✗ Open</span>')
    is_resolved.short_description = 'Resolved'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('user', 'resolved_by')


@admin.register(ErrorLog)
class ErrorLogAdmin(admin.ModelAdmin):
    list_display = ['error', 'timestamp', 'level', 'message_preview', 'user']
    list_filter = ['level', 'timestamp', 'error__module', 'error__category']
    search_fields = ['error__title', 'message', 'error__error_id']
    readonly_fields = ['error', 'timestamp', 'level', 'message', 'data', 'user']
    
    def message_preview(self, obj):
        """Display truncated message"""
        if len(obj.message) > 100:
            return obj.message[:100] + "..."
        return obj.message
    message_preview.short_description = 'Message'
    
    def get_queryset(self, request):
        return super().get_queryset(request).select_related('error', 'user')


@admin.register(ErrorPattern)
class ErrorPatternAdmin(admin.ModelAdmin):
    list_display = ['name', 'category', 'severity', 'module', 'auto_resolve', 'is_active', 'created_at']
    list_filter = ['category', 'severity', 'module', 'auto_resolve', 'is_active', 'created_at']
    search_fields = ['name', 'pattern', 'category']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'pattern', 'category', 'severity', 'module', 'is_active')
        }),
        ('Auto-Resolution', {
            'fields': ('auto_resolve', 'resolution_notes')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )
