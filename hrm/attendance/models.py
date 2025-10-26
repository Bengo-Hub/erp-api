from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
from hrm.employees.models import Employee
from core.models import Projects
from django.contrib.auth import get_user_model

User = get_user_model()


class WorkShift(models.Model):
    """
    Work shift configuration with support for day-wise schedules.
    Can be used for regular shifts (Monday-Friday) or flexible schedules.
    """
    name = models.CharField(max_length=100)
    # Legacy fields - kept for backward compatibility but made optional
    start_time = models.TimeField(blank=True, null=True, help_text="Legacy: Default start time")
    end_time = models.TimeField(blank=True, null=True, help_text="Legacy: Default end time")
    grace_minutes = models.PositiveIntegerField(default=0, help_text="Grace period for late arrivals in minutes")
    total_hours_per_week = models.DecimalField(
        max_digits=5, 
        decimal_places=2, 
        default=Decimal('40.00'),
        help_text="Total expected work hours per week"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        db_table = "hrm_work_shifts"
        ordering = ["id"]
        indexes = [
            models.Index(fields=['name'], name='idx_work_shift_name'),
            models.Index(fields=['created_at'], name='idx_work_shift_created_at'),
        ]


class WorkShiftSchedule(models.Model):
    """
    Day-wise schedule for a work shift.
    Allows different start/end times and break hours for each day of the week.
    """
    DAY_CHOICES = (
        ('Monday', 'Monday'),
        ('Tuesday', 'Tuesday'),
        ('Wednesday', 'Wednesday'),
        ('Thursday', 'Thursday'),
        ('Friday', 'Friday'),
        ('Saturday', 'Saturday'),
        ('Sunday', 'Sunday'),
    )
    
    work_shift = models.ForeignKey(
        WorkShift, 
        on_delete=models.CASCADE, 
        related_name='schedule'
    )
    day = models.CharField(max_length=10, choices=DAY_CHOICES)
    start_time = models.TimeField(help_text="Shift start time for this day")
    end_time = models.TimeField(help_text="Shift end time for this day")
    break_hours = models.DecimalField(
        max_digits=3, 
        decimal_places=1, 
        default=Decimal('0.0'),
        help_text="Break hours for this day"
    )
    is_working_day = models.BooleanField(default=True, help_text="Whether this is a working day")
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.work_shift.name} - {self.day}"

    class Meta:
        db_table = "hrm_work_shift_schedules"
        unique_together = ("work_shift", "day")
        ordering = ["work_shift", "day"]
        indexes = [
            models.Index(fields=['work_shift', 'day'], name='idx_shift_schedule_shift_day'),
            models.Index(fields=['day'], name='idx_shift_schedule_day'),
            models.Index(fields=['is_working_day'], name='idx_shift_schedule_working'),
        ]


class OffDay(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="off_days")
    date = models.DateField()
    reason = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"{self.employee.pk} - {self.date}"

    class Meta:
        db_table = "hrm_off_days"
        unique_together = ("employee", "date")
        indexes = [
            models.Index(fields=["employee", "date"], name="idx_offday_emp_date"),
            models.Index(fields=["employee"], name="idx_offday_employee"),
            models.Index(fields=["date"], name="idx_offday_date"),
            models.Index(fields=["created_at"], name="idx_offday_created_at"),
        ]


class AttendanceRecord(models.Model):
    STATUS_CHOICES = (
        ("present", "Present"),
        ("absent", "Absent"),
        ("late", "Late"),
        ("half-day", "Half Day"),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="attendance_records")
    work_shift = models.ForeignKey(WorkShift, on_delete=models.SET_NULL, blank=True, null=True)
    date = models.DateField(default=timezone.localdate)
    check_in = models.DateTimeField(blank=True, null=True)
    check_out = models.DateTimeField(blank=True, null=True)
    # Kenyan market: biometric and GPS capture
    biometric_id = models.CharField(max_length=100, blank=True, null=True, help_text="Biometric device/user ID for attendance capture")
    gps_latitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True, help_text="GPS latitude at check-in/out")
    gps_longitude = models.DecimalField(max_digits=9, decimal_places=6, blank=True, null=True, help_text="GPS longitude at check-in/out")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="present")
    total_seconds_worked = models.PositiveIntegerField(default=0)
    notes = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"{self.employee.pk} - {self.date}"

    class Meta:
        db_table = "hrm_attendance_records"
        unique_together = ("employee", "date")
        ordering = ["-date", "employee_id"]
        indexes = [
            models.Index(fields=["employee", "date"], name="idx_att_emp_date"),
            models.Index(fields=["date"], name="idx_att_date"),
            models.Index(fields=["employee"], name="idx_attendance_employee"),
            models.Index(fields=["work_shift"], name="idx_attendance_work_shift"),
            models.Index(fields=["check_in"], name="idx_attendance_check_in"),
            models.Index(fields=["check_out"], name="idx_attendance_check_out"),
            models.Index(fields=["biometric_id"], name="idx_attendance_biometric"),
            models.Index(fields=["status"], name="idx_attendance_status"),
            models.Index(fields=["created_at"], name="idx_attendance_created_at"),
        ]


class AttendanceRule(models.Model):
    """
    Business rules for attendance management including late policies,
    overtime rules, and attendance thresholds.
    """
    RULE_TYPE_CHOICES = (
        ('late_policy', 'Late Arrival Policy'),
        ('overtime_policy', 'Overtime Policy'),
        ('absenteeism_policy', 'Absenteeism Policy'),
        ('work_hours_policy', 'Work Hours Policy'),
        ('break_policy', 'Break Time Policy'),
        ('holiday_policy', 'Holiday Policy'),
    )
    
    name = models.CharField(max_length=100, help_text="Name of the attendance rule")
    rule_type = models.CharField(max_length=30, choices=RULE_TYPE_CHOICES)
    description = models.TextField(blank=True, null=True, help_text="Detailed description of the rule")
    
    # Rule configuration
    is_active = models.BooleanField(default=True, help_text="Whether this rule is currently active")
    priority = models.PositiveIntegerField(default=100, help_text="Priority order for rule application (higher = more important)")
    
    # Late arrival policy
    late_threshold_minutes = models.PositiveIntegerField(default=15, help_text="Minutes after shift start time to consider as late")
    late_penalty_type = models.CharField(max_length=20, choices=[
        ('warning', 'Warning'),
        ('deduction', 'Salary Deduction'),
        ('disciplinary', 'Disciplinary Action'),
        ('none', 'No Penalty'),
    ], default='warning')
    late_penalty_value = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'), help_text="Penalty value (amount or percentage)")
    
    # Overtime policy
    overtime_threshold_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('8.00'), help_text="Hours after which overtime applies")
    overtime_rate_multiplier = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal('1.50'), help_text="Overtime pay rate multiplier")
    max_overtime_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('4.00'), help_text="Maximum overtime hours per day")
    
    # Absenteeism policy
    consecutive_absent_threshold = models.PositiveIntegerField(default=3, help_text="Consecutive absent days to trigger action")
    monthly_absent_threshold = models.PositiveIntegerField(default=5, help_text="Monthly absent days to trigger action")
    absenteeism_action = models.CharField(max_length=20, choices=[
        ('warning', 'Warning'),
        ('suspension', 'Suspension'),
        ('termination', 'Termination Review'),
        ('none', 'No Action'),
    ], default='warning')
    
    # Work hours policy
    standard_work_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('8.00'), help_text="Standard work hours per day")
    min_work_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('6.00'), help_text="Minimum work hours to count as full day")
    max_work_hours = models.DecimalField(max_digits=4, decimal_places=2, default=Decimal('12.00'), help_text="Maximum work hours per day")
    
    # Break policy
    break_duration_minutes = models.PositiveIntegerField(default=60, help_text="Total break time in minutes per day")
    break_intervals = models.JSONField(default=list, help_text="Break intervals in minutes (e.g., [30, 30] for two 30-min breaks)")
    
    # Holiday policy
    public_holidays = models.JSONField(default=list, help_text="List of public holidays (dates)")
    holiday_pay_multiplier = models.DecimalField(max_digits=3, decimal_places=2, default=Decimal('2.00'), help_text="Holiday work pay multiplier")
    
    # Business context
    business = models.ForeignKey('business.Bussiness', on_delete=models.CASCADE, related_name='attendance_rules', null=True, blank=True)
    branch = models.ForeignKey('business.Branch', on_delete=models.CASCADE, related_name='attendance_rules', null=True, blank=True, help_text="Branch where this rule applies")
    department = models.ForeignKey('core.Departments', on_delete=models.CASCADE, related_name='attendance_rules', null=True, blank=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self) -> str:
        return f"{self.name} ({self.rule_type})"
    
    class Meta:
        db_table = "hrm_attendance_rules"
        ordering = ["-priority", "name"]
        indexes = [
            models.Index(fields=["rule_type"], name="idx_attendance_rule_type"),
            models.Index(fields=["is_active"], name="idx_attendance_rule_active"),
            models.Index(fields=["priority"], name="idx_attendance_rule_priority"),
            models.Index(fields=["business"], name="idx_attendance_rule_business"),
            models.Index(fields=["branch"], name="idx_attendance_rule_branch"),
            models.Index(fields=["department"], name="idx_attendance_rule_department"),
            models.Index(fields=["created_at"], name="idx_attendance_rule_created_at"),
        ]


class ShiftRotation(models.Model):
    """Shift rotation patterns for managing rotating shifts"""
    title = models.CharField(max_length=255)
    shifts = models.ManyToManyField(WorkShift, related_name='rotations', blank=True)
    current_active_shift = models.ForeignKey(WorkShift, on_delete=models.SET_NULL, null=True, blank=True, related_name='current_rotations')
    last_shift = models.ForeignKey(WorkShift, on_delete=models.SET_NULL, null=True, blank=True, related_name='previous_rotations')
    run_duration = models.PositiveIntegerField(default=2, help_text=_('Duration to run each shift'))
    run_unit = models.CharField(max_length=20, choices=[
        ('Day', 'Day'),
        ('Days', 'Days'),
        ('Week', 'Week'),
        ('Weeks', 'Weeks'),
        ('Month', 'Month'),
        ('Months', 'Months')
    ], default='Months')
    break_duration = models.PositiveIntegerField(default=1, help_text=_('Break duration between shifts'))
    break_unit = models.CharField(max_length=20, choices=[
        ('Day', 'Day'),
        ('Days', 'Days'),
        ('Week', 'Week'),
        ('Weeks', 'Weeks'),
        ('Month', 'Month'),
        ('Months', 'Months')
    ], default='Day')
    next_change_date = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'hrm_shift_rotations'
        verbose_name = _('Shift Rotation')
        verbose_name_plural = _('Shift Rotations')
        indexes = [
            models.Index(fields=['title'], name='idx_shift_rotation_title'),
            models.Index(fields=['is_active'], name='idx_shift_rotation_active'),
        ]

    def __str__(self):
        return self.title


class ESSSettings(models.Model):
    """
    Global ESS (Employee Self-Service) configuration settings.
    Singleton model - only one instance should exist.
    """
    
    # Shift-based login restrictions
    enable_shift_based_restrictions = models.BooleanField(
        default=True,
        verbose_name="Enable Shift-Based Login Restrictions",
        help_text="When enabled, employees can only login during their assigned shift working days (excluding off days and leave)"
    )
    
    # Role exemptions
    exempt_roles = models.ManyToManyField(
        'auth.Group',
        blank=True,
        verbose_name="Exempt Roles/Groups",
        help_text="User groups/roles that are exempt from shift-based login restrictions"
    )
    
    # App Access Permissions (From ESS Portal UI)
    allow_payslip_view = models.BooleanField(
        default=True,
        verbose_name="Allow Payslip View",
        help_text="Allow employees to view and download their payslips"
    )
    
    allow_leave_application = models.BooleanField(
        default=True,
        verbose_name="Allow Leave Application",
        help_text="Allow employees to submit leave requests"
    )
    
    allow_timesheet_application = models.BooleanField(
        default=False,
        verbose_name="Allow Timesheet Application",
        help_text="Allow employees to submit timesheets"
    )
    
    allow_overtime_application = models.BooleanField(
        default=False,
        verbose_name="Allow Overtime Application",
        help_text="Allow employees to apply for overtime"
    )
    
    allow_advance_salary_application = models.BooleanField(
        default=False,
        verbose_name="Allow Advance Salary Application",
        help_text="Allow employees to request salary advances"
    )
    
    allow_losses_damage_submission = models.BooleanField(
        default=False,
        verbose_name="Allow Losses/Damage Submission",
        help_text="Allow employees to report losses and damages"
    )
    
    allow_expense_claims_application = models.BooleanField(
        default=False,
        verbose_name="Allow Expense Claims Application",
        help_text="Allow employees to submit expense claim requests"
    )
    
    # Additional ESS settings
    require_password_change_on_first_login = models.BooleanField(
        default=True,
        verbose_name="Require Password Change on First Login",
        help_text="Force employees to change their password on first ESS login"
    )
    
    session_timeout_minutes = models.PositiveIntegerField(
        default=60,
        verbose_name="Session Timeout (Minutes)",
        help_text="Number of minutes before an inactive ESS session expires"
    )
    
    allow_weekend_login = models.BooleanField(
        default=False,
        verbose_name="Allow Weekend Login",
        help_text="Override shift restrictions and allow login on weekends for all employees"
    )
    
    max_failed_login_attempts = models.PositiveIntegerField(
        default=5,
        verbose_name="Max Failed Login Attempts",
        help_text="Number of failed login attempts before account is locked"
    )
    
    account_lockout_duration_minutes = models.PositiveIntegerField(
        default=30,
        verbose_name="Account Lockout Duration (Minutes)",
        help_text="Duration to lock account after max failed login attempts"
    )
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'ess_settings'
        verbose_name = 'ESS Settings'
        verbose_name_plural = 'ESS Settings'
        indexes = [
            models.Index(fields=['enable_shift_based_restrictions'], name='idx_ess_shift_restrict'),
            models.Index(fields=['created_at'], name='idx_ess_created_at'),
        ]
    
    def __str__(self):
        return "ESS Settings"
    
    def save(self, *args, **kwargs):
        """Ensure only one instance exists (Singleton pattern)"""
        self.pk = 1
        super().save(*args, **kwargs)
    
    @classmethod
    def load(cls):
        """Load or create the singleton ESS settings instance"""
        obj, created = cls.objects.get_or_create(pk=1)
        return obj
    
    def is_role_exempt(self, user):
        """Check if user's roles/groups are exempt from restrictions"""
        if not user or not user.is_authenticated:
            return False
        
        user_groups = user.groups.all()
        exempt_group_ids = self.exempt_roles.values_list('id', flat=True)
        
        return user_groups.filter(id__in=exempt_group_ids).exists()


class Timesheet(models.Model):
    """
    Employee timesheet for tracking work hours and activities
    """
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected')
    ]
    
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name='timesheets'
    )
    approver = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_timesheets'
    )
    period_start = models.DateField(help_text='Start date of timesheet period')
    period_end = models.DateField(help_text='End date of timesheet period')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    submission_date = models.DateTimeField(null=True, blank=True)
    approval_date = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True, null=True)
    total_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    total_overtime_hours = models.DecimalField(max_digits=8, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_active = models.BooleanField(default=True)
    
    class Meta:
        verbose_name = 'Timesheet'
        verbose_name_plural = 'Timesheets'
        ordering = ['-period_start', '-created_at']
        unique_together = [['employee', 'period_start', 'period_end']]
    
    def __str__(self):
        return f"{self.employee.user.get_full_name()} - {self.period_start} to {self.period_end}"
    
    def calculate_totals(self):
        """Calculate total hours from timesheet entries"""
        entries = self.entries.all()
        self.total_hours = sum(entry.regular_hours for entry in entries)
        self.total_overtime_hours = sum(entry.overtime_hours for entry in entries)
        self.save()


class TimesheetEntry(models.Model):
    """
    Individual daily entries within a timesheet
    """
    timesheet = models.ForeignKey(
        Timesheet,
        on_delete=models.CASCADE,
        related_name='entries'
    )
    date = models.DateField()
    project = models.ForeignKey(
        Projects,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='timesheet_entries'
    )
    task_description = models.TextField()
    regular_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    break_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    notes = models.TextField(blank=True, null=True)
    
    class Meta:
        verbose_name = 'Timesheet Entry'
        verbose_name_plural = 'Timesheet Entries'
        ordering = ['date']
        unique_together = [['timesheet', 'date']]
    
    def __str__(self):
        return f"{self.timesheet.employee.user.get_full_name()} - {self.date}"
    
    @property
    def total_hours(self):
        """Calculate total hours for this entry"""
        return self.regular_hours + self.overtime_hours
