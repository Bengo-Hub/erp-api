"""
Serializers for centralized task management
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Task, TaskLog, TaskTemplate

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """User serializer for task relationships"""
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class TaskLogSerializer(serializers.ModelSerializer):
    """Task log serializer"""
    class Meta:
        model = TaskLog
        fields = ['id', 'timestamp', 'level', 'message', 'data']


class TaskSerializer(serializers.ModelSerializer):
    """Task serializer with related data"""
    created_by = UserSerializer(read_only=True)
    assigned_to = UserSerializer(read_only=True)
    duration = serializers.ReadOnlyField()
    is_running = serializers.ReadOnlyField()
    is_completed = serializers.ReadOnlyField()
    is_failed = serializers.ReadOnlyField()
    
    class Meta:
        model = Task
        fields = [
            'id', 'task_id', 'task_type', 'status', 'priority',
            'title', 'description', 'module', 'created_by', 'assigned_to',
            'progress', 'total_items', 'processed_items',
            'created_at', 'started_at', 'completed_at', 'estimated_duration',
            'duration', 'input_data', 'output_data', 'error_message',
            'metadata', 'tags', 'is_running', 'is_completed', 'is_failed'
        ]
        read_only_fields = [
            'id', 'task_id', 'created_at', 'started_at', 'completed_at',
            'duration', 'is_running', 'is_completed', 'is_failed'
        ]


class TaskCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating tasks"""
    class Meta:
        model = Task
        fields = [
            'task_type', 'title', 'description', 'module', 'priority',
            'input_data', 'metadata', 'tags', 'estimated_duration'
        ]


class TaskUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating tasks"""
    class Meta:
        model = Task
        fields = [
            'status', 'progress', 'total_items', 'processed_items',
            'output_data', 'error_message', 'assigned_to'
        ]


class TaskTemplateSerializer(serializers.ModelSerializer):
    """Task template serializer"""
    class Meta:
        model = TaskTemplate
        fields = [
            'id', 'name', 'task_type', 'module', 'title_template',
            'description_template', 'input_schema', 'default_priority',
            'estimated_duration', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']


class TaskExecutionSerializer(serializers.Serializer):
    """Serializer for executing tasks"""
    function_name = serializers.CharField(max_length=255)
    args = serializers.ListField(default=list)
    kwargs = serializers.DictField(default=dict)
    input_data = serializers.DictField(default=dict)