from django.contrib import admin
from .models import JobPosting, Candidate, Application


@admin.register(JobPosting)
class JobPostingAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "posted_at", "closed_at")
    search_fields = ("title", "department", "location")


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("full_name", "email", "created_at")
    search_fields = ("full_name", "email")


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("job", "candidate", "status", "applied_at")
    list_filter = ("status",)
