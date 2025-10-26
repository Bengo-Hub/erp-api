from django.contrib import admin
from .models import (
    WorkShift, WorkShiftSchedule, ShiftRotation, OffDay, AttendanceRecord, 
    AttendanceRule, ESSSettings, Timesheet, TimesheetEntry
)


class WorkShiftScheduleInline(admin.TabularInline):
    """Inline admin for work shift schedules"""
    model = WorkShiftSchedule
    extra = 1
    fields = ['day', 'start_time', 'end_time', 'break_hours', 'is_working_day']
    ordering = ['day']


@admin.register(WorkShift)
class WorkShiftAdmin(admin.ModelAdmin):
    list_display = ['name', 'total_hours_per_week', 'grace_minutes', 'created_at']
    list_filter = ['created_at']
    search_fields = ['name']
    ordering = ['name']
    inlines = [WorkShiftScheduleInline]
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('name', 'total_hours_per_week', 'grace_minutes')
        }),
        ('Legacy Fields (Optional)', {
            'fields': ('start_time', 'end_time'),
            'classes': ('collapse',)
        }),
    )


@admin.register(WorkShiftSchedule)
class WorkShiftScheduleAdmin(admin.ModelAdmin):
    list_display = ['work_shift', 'day', 'start_time', 'end_time', 'break_hours', 'is_working_day']
    list_filter = ['day', 'is_working_day', 'work_shift']
    search_fields = ['work_shift__name']
    ordering = ['work_shift', 'day']


@admin.register(ShiftRotation)
class ShiftRotationAdmin(admin.ModelAdmin):
    list_display = ['title', 'current_active_shift', 'run_duration', 'run_unit', 'is_active', 'next_change_date']
    list_filter = ['is_active', 'run_unit', 'created_at']
    search_fields = ['title']
    ordering = ['-created_at']
    filter_horizontal = ['shifts']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('Basic Information', {
            'fields': ('title', 'is_active')
        }),
        ('Shift Configuration', {
            'fields': ('shifts', 'current_active_shift', 'last_shift')
        }),
        ('Rotation Schedule', {
            'fields': ('run_duration', 'run_unit', 'break_duration', 'break_unit', 'next_change_date')
        }),
        ('Metadata', {
            'fields': ('created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


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


@admin.register(ESSSettings)
class ESSSettingsAdmin(admin.ModelAdmin):
    """Admin interface for ESS Settings (Singleton)"""
    
    list_display = [
        'enable_shift_based_restrictions',
        'allow_payslip_view',
        'allow_leave_application',
        'allow_weekend_login',
        'session_timeout_minutes',
        'updated_at'
    ]
    
    filter_horizontal = ['exempt_roles']
    
    fieldsets = (
        ('Login Restrictions', {
            'fields': (
                'enable_shift_based_restrictions',
                'exempt_roles',
                'allow_weekend_login',
            ),
            'description': 'Configure shift-based login restrictions and exemptions'
        }),
        ('App Access Permissions', {
            'fields': (
                'allow_payslip_view',
                'allow_leave_application',
                'allow_timesheet_application',
                'allow_overtime_application',
                'allow_advance_salary_application',
                'allow_losses_damage_submission',
                'allow_expense_claims_application',
            ),
            'description': 'Control what employees can do on the ESS Portal'
        }),
        ('Password & Security', {
            'fields': (
                'require_password_change_on_first_login',
                'max_failed_login_attempts',
                'account_lockout_duration_minutes',
            )
        }),
        ('Session Management', {
            'fields': (
                'session_timeout_minutes',
            )
        }),
    )
    
    def has_add_permission(self, request):
        """Prevent adding more than one ESS Settings instance"""
        return not ESSSettings.objects.exists()
    
    def has_delete_permission(self, request, obj=None):
        """Prevent deletion of ESS Settings"""
        return False


class TimesheetEntryInline(admin.TabularInline):
    """Inline admin for timesheet entries"""
    model = TimesheetEntry
    extra = 1
    fields = ['date', 'project', 'task_description', 'regular_hours', 'overtime_hours', 'break_hours', 'notes']
    ordering = ['date']


@admin.register(Timesheet)
class TimesheetAdmin(admin.ModelAdmin):
    list_display = ['id', 'employee', 'period_start', 'period_end', 'status', 'total_hours', 'total_overtime_hours', 'submission_date', 'approver']
    list_filter = ['status', 'period_start', 'period_end', 'is_active']
    search_fields = ['employee__user__first_name', 'employee__user__last_name', 'employee__user__email']
    readonly_fields = ['created_at', 'updated_at', 'total_hours', 'total_overtime_hours']
    inlines = [TimesheetEntryInline]
    date_hierarchy = 'period_start'
    
    fieldsets = (
        ('Employee Information', {
            'fields': ('employee', 'approver')
        }),
        ('Period', {
            'fields': ('period_start', 'period_end')
        }),
        ('Status', {
            'fields': ('status', 'submission_date', 'approval_date', 'rejection_reason')
        }),
        ('Hours Summary', {
            'fields': ('total_hours', 'total_overtime_hours', 'notes')
        }),
        ('Metadata', {
            'fields': ('is_active', 'created_at', 'updated_at'),
            'classes': ('collapse',)
        }),
    )


@admin.register(TimesheetEntry)
class TimesheetEntryAdmin(admin.ModelAdmin):
    list_display = ['id', 'timesheet', 'date', 'project', 'regular_hours', 'overtime_hours', 'total_hours']
    list_filter = ['date', 'project']
    search_fields = ['timesheet__employee__user__first_name', 'timesheet__employee__user__last_name', 'task_description']
    date_hierarchy = 'date'
    
    fieldsets = (
        ('Timesheet Information', {
            'fields': ('timesheet', 'date', 'project')
        }),
        ('Work Details', {
            'fields': ('task_description', 'regular_hours', 'overtime_hours', 'break_hours', 'notes')
        }),
    )