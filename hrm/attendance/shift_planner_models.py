"""
Shift planner / roster models — adapted from the pos-api design (cycle-based rotation +
per-date overrides + explicit staff assignment) which the ERP previously lacked.

Separation of concerns (mirrors pos-service):
  - ShiftRoster      : a recurring pattern resolved by cycle_days + start_date (modulo arithmetic)
  - ShiftRosterSlot  : one employee's hours for a given 1-based cycle_day (or an off day)
  - ShiftAssignment  : the missing link — assigns an employee to a roster for an active window
  - StaffShiftOverride: a date-specific exception (off_duty / manual_shift / half_day) with approval

Kept distinct from the legacy org-level ``ShiftRotation`` (time-unit rotation between WorkShifts),
which models a different concept and is left untouched.
"""
from __future__ import annotations

from django.db import models
from django.contrib.auth import get_user_model

from hrm.employees.models import Employee

User = get_user_model()


class ShiftRoster(models.Model):
    """A recurring roster pattern. Calendar dates resolve to a 1-based ``cycle_day`` via
    ``((date - start_date).days % cycle_days) + 1`` (same approach as pos-api)."""
    name = models.CharField(max_length=255)
    outlet_id = models.UUIDField(null=True, blank=True, db_index=True, help_text="Optional outlet scope")
    cycle_days = models.PositiveIntegerField(default=14, help_text="Length of the rotation cycle in days")
    start_date = models.DateField(help_text="Calendar anchor; cycle_day positions resolve from this date")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "attendance"
        db_table = "hrm_shift_rosters"
        ordering = ["name"]
        indexes = [models.Index(fields=["is_active"], name="idx_shift_roster_active")]

    def __str__(self) -> str:
        return self.name

    def cycle_day_for(self, on_date) -> int:
        """1-based cycle position for a calendar date."""
        days = (on_date - self.start_date).days
        return (days % self.cycle_days) + 1


class ShiftRosterSlot(models.Model):
    """An employee's scheduled hours for one cycle_day of a roster (or an off day)."""
    roster = models.ForeignKey(ShiftRoster, on_delete=models.CASCADE, related_name="slots")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="roster_slots")
    cycle_day = models.PositiveIntegerField(help_text="1-based position within the roster cycle")
    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)
    is_off_day = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        app_label = "attendance"
        db_table = "hrm_shift_roster_slots"
        constraints = [
            models.UniqueConstraint(fields=["roster", "employee", "cycle_day"], name="uniq_roster_emp_cycleday"),
        ]
        indexes = [models.Index(fields=["roster", "cycle_day"], name="idx_roster_slot_day")]

    def __str__(self) -> str:
        return f"{self.employee} D{self.cycle_day}"


class ShiftAssignment(models.Model):
    """Assigns an employee to a roster for an active date window (the previously-missing link)."""
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="shift_assignments")
    roster = models.ForeignKey(ShiftRoster, on_delete=models.CASCADE, related_name="assignments")
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True, help_text="Open-ended if blank")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "attendance"
        db_table = "hrm_shift_assignments"
        ordering = ["-start_date"]
        indexes = [
            models.Index(fields=["employee", "is_active"], name="idx_shift_assign_emp"),
            models.Index(fields=["roster"], name="idx_shift_assign_roster"),
        ]

    def __str__(self) -> str:
        return f"{self.employee} → {self.roster}"

    def covers(self, on_date) -> bool:
        if not self.is_active or on_date < self.start_date:
            return False
        return self.end_date is None or on_date <= self.end_date


class StaffShiftOverride(models.Model):
    """A one-off, date-specific exception to the roster schedule (mirrors pos StaffShiftOverride)."""
    OVERRIDE_TYPES = (
        ("off_duty", "Off Duty"),
        ("manual_shift", "Manual Shift"),
        ("half_day", "Half Day"),
    )
    STATUSES = (
        ("pending", "Pending"),
        ("approved", "Approved"),
        ("rejected", "Rejected"),
    )
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="shift_overrides")
    outlet_id = models.UUIDField(null=True, blank=True, db_index=True)
    date = models.DateField(help_text="Calendar date this override applies to")
    override_type = models.CharField(max_length=20, choices=OVERRIDE_TYPES)
    start_time = models.TimeField(null=True, blank=True, help_text="Required for manual_shift / half_day")
    end_time = models.TimeField(null=True, blank=True, help_text="Required for manual_shift / half_day")
    reason = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUSES, default="approved",
                              help_text="Manager-created auto-approve; staff self-submissions start pending")
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="created_shift_overrides")
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="approved_shift_overrides")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "attendance"
        db_table = "hrm_staff_shift_overrides"
        ordering = ["-date"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "date"], name="uniq_staff_override_date"),
        ]
        indexes = [
            models.Index(fields=["employee", "date"], name="idx_staff_override_emp_date"),
            models.Index(fields=["status"], name="idx_staff_override_status"),
        ]

    def __str__(self) -> str:
        return f"{self.employee} {self.date} ({self.override_type})"
