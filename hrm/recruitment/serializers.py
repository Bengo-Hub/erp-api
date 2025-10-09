from rest_framework import serializers
from .models import JobPosting, Candidate, Application


class JobPostingSerializer(serializers.ModelSerializer):
    class Meta:
        model = JobPosting
        fields = [
            "id",
            "title",
            "description",
            "department",
            "location",
            "status",
            "posted_at",
            "closed_at",
        ]


class CandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = ["id", "full_name", "email", "phone", "resume", "created_at"]


class ApplicationSerializer(serializers.ModelSerializer):
    class Meta:
        model = Application
        fields = [
            "id",
            "job",
            "candidate",
            "status",
            "applied_at",
            "notes",
        ]


