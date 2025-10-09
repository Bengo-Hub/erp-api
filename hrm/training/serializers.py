from rest_framework import serializers
from .models import TrainingCourse, TrainingEnrollment, TrainingEvaluation


class TrainingCourseSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingCourse
        fields = [
            "id",
            "title",
            "description",
            "start_date",
            "end_date",
            "capacity",
            "created_at",
            "updated_at",
        ]


class TrainingEnrollmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingEnrollment
        fields = ["id", "course", "employee", "status", "enrolled_at"]


class TrainingEvaluationSerializer(serializers.ModelSerializer):
    class Meta:
        model = TrainingEvaluation
        fields = ["id", "course", "employee", "rating", "feedback", "created_at"]


