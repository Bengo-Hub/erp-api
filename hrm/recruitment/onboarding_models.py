"""
Onboarding workflow — the previously-missing structured process after an Application is hired.

EmployeeOnboarding tracks a new hire's onboarding lifecycle; OnboardingTask is a checklist item
(IT / HR / Training) that is seeded from DEFAULT_ONBOARDING_TASKS when onboarding starts.
"""
from __future__ import annotations

from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model

from hrm.employees.models import Employee

User = get_user_model()

# (category, title) checklist seeded when onboarding starts.
DEFAULT_ONBOARDING_TASKS = [
    ("IT", "Provision laptop / equipment"),
    ("IT", "Create email & system accounts"),
    ("IT", "Grant building / door access"),
    ("HR", "Collect signed contract"),
    ("HR", "Collect statutory details (KRA PIN, NSSF, SHIF)"),
    ("HR", "Collect bank / payment details"),
    ("HR", "Add employee to payroll"),
    ("Training", "Company orientation"),
    ("Training", "Role-specific training"),
    ("Training", "Safety & compliance induction"),
]


class EmployeeOnboarding(models.Model):
    STATUS_CHOICES = (
        ("not_started", "Not Started"),
        ("in_progress", "In Progress"),
        ("completed", "Completed"),
    )
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="onboardings")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="not_started")
    probation_end_date = models.DateField(blank=True, null=True)
    started_at = models.DateTimeField(blank=True, null=True)
    completed_at = models.DateTimeField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        app_label = "recruitment"
        db_table = "hrm_employee_onboarding"
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Onboarding: {self.employee} ({self.status})"

    def seed_default_tasks(self):
        """Create the default checklist if this onboarding has no tasks yet."""
        if self.tasks.exists():
            return
        OnboardingTask.objects.bulk_create([
            OnboardingTask(onboarding=self, category=cat, title=title, order=i)
            for i, (cat, title) in enumerate(DEFAULT_ONBOARDING_TASKS)
        ])
        if self.status == "not_started":
            self.status = "in_progress"
            self.started_at = timezone.now()
            self.save(update_fields=["status", "started_at", "updated_at"])

    def refresh_status(self):
        """Mark completed when all tasks are done."""
        tasks = list(self.tasks.all())
        if tasks and all(t.is_done for t in tasks):
            self.status = "completed"
            self.completed_at = self.completed_at or timezone.now()
            self.save(update_fields=["status", "completed_at", "updated_at"])


class OnboardingTask(models.Model):
    CATEGORY_CHOICES = (("IT", "IT"), ("HR", "HR"), ("Training", "Training"), ("Other", "Other"))
    onboarding = models.ForeignKey(EmployeeOnboarding, on_delete=models.CASCADE, related_name="tasks")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, default="Other")
    title = models.CharField(max_length=255)
    order = models.PositiveIntegerField(default=0)
    is_done = models.BooleanField(default=False)
    done_at = models.DateTimeField(blank=True, null=True)
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name="onboarding_tasks")

    class Meta:
        app_label = "recruitment"
        db_table = "hrm_onboarding_tasks"
        ordering = ["order", "id"]

    def __str__(self) -> str:
        return f"[{self.category}] {self.title}"
