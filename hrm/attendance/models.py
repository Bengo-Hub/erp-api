from django.db import models
from django.utils import timezone
from decimal import Decimal
from hrm.employees.models import Employee


class WorkShift(models.Model):
    name = models.CharField(max_length=100)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_minutes = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return self.name

    class Meta:
        db_table = "hrm_work_shifts"
        ordering = ["id"]
        indexes = [
            models.Index(fields=['name'], name='idx_work_shift_name'),
            models.Index(fields=['start_time'], name='idx_work_shift_start_time'),
            models.Index(fields=['end_time'], name='idx_work_shift_end_time'),
            models.Index(fields=['created_at'], name='idx_work_shift_created_at'),
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