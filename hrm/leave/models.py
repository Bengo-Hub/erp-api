from django.db import models
from django.utils import timezone
from authmanagement.models import CustomUser
from hrm.employees.models import Employee
from django.core.validators import MinValueValidator
from django.utils.translation import gettext_lazy as _
from decimal import Decimal


class LeaveCategory(models.Model):
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    class Meta:
        verbose_name_plural = "Leave Categories"
        ordering = ['name']

class LeaveEntitlement(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_entitlements')
    category = models.ForeignKey(LeaveCategory, on_delete=models.CASCADE)
    days_entitled = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0)])
    year = models.IntegerField()
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee} - {self.category} ({self.year})"

    class Meta:
        unique_together = ['employee', 'category', 'year']
        ordering = ['-year', 'employee']

class LeaveRequest(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('cancelled', 'Cancelled'),
    ]

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    category = models.ForeignKey(LeaveCategory, on_delete=models.CASCADE)
    start_date = models.DateField()
    end_date = models.DateField()
    days_requested = models.DecimalField(max_digits=5, decimal_places=2, validators=[MinValueValidator(0)])
    reason = models.TextField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    approved_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_leaves')
    approved_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee} - {self.category} ({self.start_date} to {self.end_date})"

    class Meta:
        ordering = ['-created_at']

class LeaveBalance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_balances')
    category = models.ForeignKey(LeaveCategory, on_delete=models.CASCADE)
    year = models.IntegerField()
    days_entitled = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(0)])
    days_taken = models.DecimalField(max_digits=7, decimal_places=2, default=Decimal('0.00'), validators=[MinValueValidator(0)])
    days_remaining = models.DecimalField(max_digits=7, decimal_places=2, validators=[MinValueValidator(0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee} - {self.category} ({self.year})"

    class Meta:
        unique_together = ['employee', 'category', 'year']
        ordering = ['-year', 'employee']

class LeaveLog(models.Model):
    ACTION_CHOICES = [
        ('create', 'Create'),
        ('update', 'Update'),
        ('approve', 'Approve'),
        ('reject', 'Reject'),
        ('cancel', 'Cancel'),
    ]

    leave_request = models.ForeignKey(LeaveRequest, on_delete=models.CASCADE, related_name='logs')
    action = models.CharField(max_length=20, choices=ACTION_CHOICES)
    description = models.TextField()
    user = models.ForeignKey(CustomUser, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.leave_request.employee.user.get_full_name()} - {self.action} - {self.created_at}"


class PublicHoliday(models.Model):
    """Kenyan public holidays (national or county-specific)."""
    name = models.CharField(max_length=150)
    date = models.DateField()
    is_national = models.BooleanField(default=True)
    county = models.CharField(max_length=100, blank=True, null=True, help_text=_('If not national, the county this holiday applies to'))
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'hrm_public_holidays'
        verbose_name = _('Public Holiday')
        verbose_name_plural = _('Public Holidays')
        ordering = ['-date']
        unique_together = [('date', 'county')]
        indexes = [
            models.Index(fields=['date'], name='idx_holiday_date'),
            models.Index(fields=['is_national'], name='idx_holiday_national'),
            models.Index(fields=['county'], name='idx_holiday_county'),
        ]

    def __str__(self):
        scope = 'National' if self.is_national else (self.county or 'County')
        return f"{self.name} ({scope}) {self.date}"
