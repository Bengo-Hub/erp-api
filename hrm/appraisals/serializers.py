from rest_framework import serializers
from .models import (
    AppraisalCycle, AppraisalTemplate, AppraisalQuestion,
    Appraisal, AppraisalResponse, Goal, GoalProgress
)
from hrm.employees.serializers import EmployeeSerializer
from authmanagement.serializers import UserSerializer

class AppraisalCycleSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    locations = serializers.SerializerMethodField()
    status_display = serializers.CharField(source='get_status_display', read_only=True)

    class Meta:
        model = AppraisalCycle
        fields = [
            'id', 'name', 'description', 'start_date', 'end_date',
            'due_date', 'status', 'status_display', 'locations',
            'created_by', 'created_at', 'updated_at'
        ]

    def get_locations(self, obj):
        return [{'id': loc.id, 'name': loc.name} for loc in obj.locations.all()]

class AppraisalTemplateSerializer(serializers.ModelSerializer):
    created_by = UserSerializer(read_only=True)
    questions_count = serializers.SerializerMethodField()

    class Meta:
        model = AppraisalTemplate
        fields = [
            'id', 'name', 'description', 'is_active',
            'created_by', 'created_at', 'updated_at',
            'questions_count'
        ]

    def get_questions_count(self, obj):
        return obj.questions.count()

class AppraisalQuestionSerializer(serializers.ModelSerializer):
    question_type_display = serializers.CharField(source='get_question_type_display', read_only=True)

    class Meta:
        model = AppraisalQuestion
        fields = [
            'id', 'template', 'question_text', 'question_type',
            'question_type_display', 'is_required', 'order',
            'created_at', 'updated_at'
        ]

class AppraisalSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    evaluator = EmployeeSerializer(read_only=True)
    template = AppraisalTemplateSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    responses_count = serializers.SerializerMethodField()

    class Meta:
        model = Appraisal
        fields = [
            'id', 'cycle', 'employee', 'evaluator', 'template',
            'status', 'status_display', 'overall_rating',
            'comments', 'created_at', 'updated_at', 'responses_count'
        ]

    def get_responses_count(self, obj):
        return obj.responses.count()

class AppraisalResponseSerializer(serializers.ModelSerializer):
    question = AppraisalQuestionSerializer(read_only=True)

    class Meta:
        model = AppraisalResponse
        fields = [
            'id', 'appraisal', 'question', 'response',
            'rating', 'created_at', 'updated_at'
        ]

class GoalSerializer(serializers.ModelSerializer):
    employee = EmployeeSerializer(read_only=True)
    created_by = UserSerializer(read_only=True)
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    progress_updates = serializers.SerializerMethodField()

    class Meta:
        model = Goal
        fields = [
            'id', 'employee', 'title', 'description',
            'start_date', 'end_date', 'status', 'status_display',
            'progress', 'is_template', 'created_by',
            'created_at', 'updated_at', 'progress_updates'
        ]

    def get_progress_updates(self, obj):
        updates = obj.progress_updates.all()[:5]  # Get last 5 updates
        return GoalProgressSerializer(updates, many=True).data

class GoalProgressSerializer(serializers.ModelSerializer):
    updated_by = UserSerializer(read_only=True)

    class Meta:
        model = GoalProgress
        fields = [
            'id', 'goal', 'progress', 'comments',
            'updated_by', 'created_at'
        ] 