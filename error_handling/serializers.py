"""
Serializers for centralized error handling
"""
from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Error, ErrorLog, ErrorPattern

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    """User serializer for error relationships"""
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class ErrorLogSerializer(serializers.ModelSerializer):
    """Error log serializer"""
    user = UserSerializer(read_only=True)
    
    class Meta:
        model = ErrorLog
        fields = ['id', 'timestamp', 'level', 'message', 'data', 'user']


class ErrorSerializer(serializers.ModelSerializer):
    """Error serializer with related data"""
    user = UserSerializer(read_only=True)
    resolved_by = UserSerializer(read_only=True)
    is_resolved = serializers.ReadOnlyField()
    is_critical = serializers.ReadOnlyField()
    
    class Meta:
        model = Error
        fields = [
            'id', 'error_id', 'title', 'description', 'category', 'severity', 'status',
            'module', 'function_name', 'user', 'session_id', 'error_message',
            'error_traceback', 'error_data', 'request_method', 'request_url',
            'request_data', 'resolved_by', 'resolved_at', 'resolution_notes',
            'occurred_at', 'last_occurred', 'occurrence_count', 'tags', 'metadata',
            'is_resolved', 'is_critical'
        ]
        read_only_fields = [
            'id', 'error_id', 'occurred_at', 'last_occurred', 'occurrence_count',
            'is_resolved', 'is_critical'
        ]


class ErrorCreateSerializer(serializers.ModelSerializer):
    """Serializer for creating errors"""
    class Meta:
        model = Error
        fields = [
            'title', 'description', 'category', 'severity', 'module', 'function_name',
            'error_message', 'error_traceback', 'error_data', 'tags', 'metadata'
        ]


class ErrorUpdateSerializer(serializers.ModelSerializer):
    """Serializer for updating errors"""
    class Meta:
        model = Error
        fields = ['status', 'resolution_notes']


class ErrorPatternSerializer(serializers.ModelSerializer):
    """Error pattern serializer"""
    class Meta:
        model = ErrorPattern
        fields = [
            'id', 'name', 'pattern', 'category', 'severity', 'module',
            'auto_resolve', 'resolution_notes', 'is_active', 'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
