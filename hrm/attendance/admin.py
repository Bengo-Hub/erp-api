from django.contrib import admin
from .models import WorkShift, OffDay, AttendanceRecord, AttendanceRule


@admin.register(WorkShift)
class WorkShiftAdmin(admin.ModelAdmin):
    list_display = ['name', 'start_time', 'end_time', 'grace_minutes', 'created_at']
    list_filter = ['created_at']
    search_fields = ['name']
    ordering = ['name']


@admin.register(OffDay)
class OffDayAdmin(admin.ModelAdmin):
    list_display = ['employee', 'date', 'reason', 'created_at']
    list_filter = ['date', 'created_at']
    search_fields = ['employee__user__email', 'reason']
    ordering = ['-date']


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = ['employee', 'date', 'status', 'check_in', 'check_out', 'total_seconds_worked']
    list_filter = ['status', 'date', 'created_at']
    search_fields = ['employee__user__email', 'notes']
    ordering = ['-date']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(AttendanceRule)
class AttendanceRuleAdmin(admin.ModelAdmin):
    list_display = ['name', 'rule_type', 'is_active', 'priority', 'business', 'department']
    list_filter = ['rule_type', 'is_active', 'priority', 'business', 'department']
    search_fields = ['name', 'description']
    ordering = ['-priority', 'name']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'rule_type', 'description', 'is_active', 'priority')
        }),
        ('Late Arrival Policy', {
            'fields': ('late_threshold_minutes', 'late_penalty_type', 'late_penalty_value'),
            'classes': ('collapse',)
        }),
        ('Overtime Policy', {
            'fields': ('overtime_threshold_hours', 'overtime_rate_multiplier', 'max_overtime_hours'),
            'classes': ('collapse',)
        }),
        ('Absenteeism Policy', {
            'fields': ('consecutive_absent_threshold', 'monthly_absent_threshold', 'absenteeism_action'),
            'classes': ('collapse',)
        }),
        ('Work Hours Policy', {
            'fields': ('standard_work_hours', 'min_work_hours', 'max_work_hours'),
            'classes': ('collapse',)
        }),
        ('Break Policy', {
            'fields': ('break_duration_minutes', 'break_intervals'),
            'classes': ('collapse',)
        }),
        ('Holiday Policy', {
            'fields': ('public_holidays', 'holiday_pay_multiplier'),
            'classes': ('collapse',)
        }),
        ('Business Context', {
            'fields': ('business', 'department'),
            'classes': ('collapse',)
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )