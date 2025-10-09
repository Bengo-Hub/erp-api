from rest_framework import serializers
from .models import ApprovalWorkflow, ApprovalStep, Approval, ApprovalRequest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email']


class ContentTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ContentType
        fields = ['id', 'app_label', 'model']


class ApprovalStepSerializer(serializers.ModelSerializer):
    approver = UserSerializer(read_only=True)
    approver_name = serializers.SerializerMethodField()
    
    class Meta:
        model = ApprovalStep
        fields = [
            'id', 'workflow', 'step_number', 'approver', 'approver_name',
            'approver_type', 'approver_role', 'is_required', 'can_override',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']
    
    def get_approver_name(self, obj):
        if obj.approver:
            return f"{obj.approver.first_name} {obj.approver.last_name}"
        return obj.approver_role or "Role-based"


class ApprovalWorkflowSerializer(serializers.ModelSerializer):
    steps = ApprovalStepSerializer(many=True, read_only=True)
    content_type = ContentTypeSerializer(read_only=True)
    total_steps = serializers.SerializerMethodField()
    
    class Meta:
        model = ApprovalWorkflow
        fields = [
            'id', 'name', 'description', 'content_type', 'is_active',
            'requires_all_approvals', 'steps', 'total_steps', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']
    
    def get_total_steps(self, obj):
        return obj.steps.count()


class ApprovalWorkflowListSerializer(serializers.ModelSerializer):
    """Simplified serializer for list views"""
    content_type = ContentTypeSerializer(read_only=True)
    total_steps = serializers.SerializerMethodField()
    
    class Meta:
        model = ApprovalWorkflow
        fields = [
            'id', 'name', 'description', 'content_type', 'is_active',
            'total_steps', 'created_at'
        ]
    
    def get_total_steps(self, obj):
        return obj.steps.count()


class ApprovalSerializer(serializers.ModelSerializer):
    approver = UserSerializer(read_only=True)
    approver_name = serializers.SerializerMethodField()
    content_type = ContentTypeSerializer(read_only=True)
    
    class Meta:
        model = Approval
        fields = [
            'id', 'workflow', 'step', 'approver', 'approver_name',
            'content_type', 'object_id', 'status', 'notes', 'approved_at',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['approved_at', 'created_at', 'updated_at']
    
    def get_approver_name(self, obj):
        if obj.approver:
            return f"{obj.approver.first_name} {obj.approver.last_name}"
        return "Unknown"


class ApprovalRequestSerializer(serializers.ModelSerializer):
    requester = UserSerializer(read_only=True)
    workflow = ApprovalWorkflowSerializer(read_only=True)
    approvals = ApprovalSerializer(many=True, read_only=True)
    content_type = ContentTypeSerializer(read_only=True)
    current_status = serializers.SerializerMethodField()
    is_complete = serializers.SerializerMethodField()
    
    class Meta:
        model = ApprovalRequest
        fields = [
            'id', 'workflow', 'requester', 'content_type', 'object_id',
            'status', 'current_status', 'is_complete', 'requested_at',
            'completed_at', 'approvals', 'created_at', 'updated_at'
        ]
        read_only_fields = ['requested_at', 'completed_at', 'created_at', 'updated_at']
    
    def get_current_status(self, obj):
        if obj.status == 'pending':
            pending_approvals = obj.approvals.filter(status='pending').count()
            total_approvals = obj.workflow.steps.count()
            return f"Pending ({pending_approvals}/{total_approvals} approvals)"
        return obj.get_status_display()
    
    def get_is_complete(self, obj):
        return obj.status in ['approved', 'rejected']


class ApprovalRequestListSerializer(serializers.ModelSerializer):
    """Simplified serializer for list views"""
    requester = UserSerializer(read_only=True)
    workflow = ApprovalWorkflowListSerializer(read_only=True)
    content_type = ContentTypeSerializer(read_only=True)
    
    class Meta:
        model = ApprovalRequest
        fields = [
            'id', 'workflow', 'requester', 'content_type', 'object_id',
            'status', 'requested_at', 'completed_at', 'created_at'
        ]
