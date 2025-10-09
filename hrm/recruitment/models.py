from django.db import models
from django.utils import timezone
from hrm.employees.models import Employee


class JobPosting(models.Model):
    STATUS_CHOICES = (
        ("draft", "Draft"),
        ("open", "Open"),
        ("closed", "Closed"),
        ("archived", "Archived"),
    )
    title = models.CharField(max_length=255)
    description = models.TextField()
    department = models.CharField(max_length=255, blank=True, null=True)
    location = models.CharField(max_length=255, blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="draft")
    posted_at = models.DateTimeField(default=timezone.now)
    closed_at = models.DateTimeField(blank=True, null=True)

    def __str__(self) -> str:
        return self.title

    class Meta:
        db_table = "hrm_recruitment_job_postings"
        ordering = ["-posted_at"]


class Candidate(models.Model):
    full_name = models.CharField(max_length=255)
    email = models.EmailField()
    phone = models.CharField(max_length=50, blank=True, null=True)
    resume = models.FileField(upload_to="recruitment/resumes", blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return self.full_name

    class Meta:
        db_table = "hrm_recruitment_candidates"
        ordering = ["-created_at"]


class Application(models.Model):
    STATUS_CHOICES = (
        ("applied", "Applied"),
        ("screening", "Screening"),
        ("interview", "Interview"),
        ("offered", "Offered"),
        ("hired", "Hired"),
        ("rejected", "Rejected"),
    )
    job = models.ForeignKey(JobPosting, on_delete=models.CASCADE, related_name="applications")
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE, related_name="applications")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="applied")
    applied_at = models.DateTimeField(default=timezone.now)
    notes = models.TextField(blank=True, null=True)

    def __str__(self) -> str:
        return f"{self.candidate.full_name} - {self.job.title}"

    class Meta:
        db_table = "hrm_recruitment_applications"
        ordering = ["-applied_at"]
        indexes = [
            models.Index(fields=["job", "status"], name="idx_app_job_status"),
        ]

