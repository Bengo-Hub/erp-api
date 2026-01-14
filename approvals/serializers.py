from rest_framework import serializers
from .models import ApprovalWorkflow, ApprovalStep, Approval, ApprovalRequest
from django.contrib.auth import get_user_model
from django.contrib.contenttypes.models import ContentType

User = get_user_model()


class UserSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'first_name', 'last_name', 'email', 'name']

    def get_name(self, obj):
        return f"{obj.first_name} {obj.last_name}".strip() or obj.username


class ContentTypeSerializer(serializers.ModelSerializer):
    name = serializers.SerializerMethodField()

    class Meta:
        model = ContentType
        fields = ['id', 'app_label', 'model', 'name']

    def get_name(self, obj):
        return obj.name or f"{obj.app_label}.{obj.model}"


class ApprovalStepSerializer(serializers.ModelSerializer):
    approver_user_detail = UserSerializer(source='approver_user', read_only=True)
    approver_name = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalStep
        fields = [
            'id', 'workflow', 'step_number', 'name', 'approver_type',
            'approver_user', 'approver_user_detail', 'approver_name',
            'approver_role', 'approver_department', 'is_required',
            'can_delegate', 'auto_approve', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_approver_name(self, obj):
        if obj.approver_user:
            return f"{obj.approver_user.first_name} {obj.approver_user.last_name}".strip()
        if obj.approver_role:
            return obj.approver_role.replace('_', ' ').title()
        if obj.approver_type == 'department_head':
            return "Department Head"
        return obj.approver_type.replace('_', ' ').title()


class ApprovalWorkflowSerializer(serializers.ModelSerializer):
    steps = ApprovalStepSerializer(many=True, read_only=True)
    total_steps = serializers.SerializerMethodField()
    workflow_type_display = serializers.CharField(source='get_workflow_type_display', read_only=True)

    class Meta:
        model = ApprovalWorkflow
        fields = [
            'id', 'name', 'workflow_type', 'workflow_type_display', 'description',
            'requires_multiple_approvals', 'approval_order_matters',
            'auto_approve_on_threshold', 'approval_threshold',
            'is_active', 'steps', 'total_steps', 'created_at', 'updated_at'
        ]
        read_only_fields = ['created_at', 'updated_at']

    def get_total_steps(self, obj):
        return obj.steps.count()


class ApprovalWorkflowListSerializer(serializers.ModelSerializer):
    """Simplified serializer for list views"""
    total_steps = serializers.SerializerMethodField()
    workflow_type_display = serializers.CharField(source='get_workflow_type_display', read_only=True)

    class Meta:
        model = ApprovalWorkflow
        fields = [
            'id', 'name', 'workflow_type', 'workflow_type_display', 'description',
            'is_active', 'total_steps', 'created_at'
        ]

    def get_total_steps(self, obj):
        return obj.steps.count()


class ApprovalSerializer(serializers.ModelSerializer):
    approver_detail = UserSerializer(source='approver', read_only=True)
    approver_name = serializers.SerializerMethodField()
    content_type_detail = ContentTypeSerializer(source='content_type', read_only=True)
    step_detail = ApprovalStepSerializer(source='step', read_only=True)

    class Meta:
        model = Approval
        fields = [
            'id', 'workflow', 'step', 'step_detail', 'approver', 'approver_detail',
            'approver_name', 'delegated_to', 'content_type', 'content_type_detail',
            'object_id', 'status', 'notes', 'comments', 'approval_amount',
            'is_auto_approved', 'requested_at', 'approved_at', 'rejected_at',
            'delegated_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['requested_at', 'approved_at', 'rejected_at',
                           'delegated_at', 'created_at', 'updated_at']

    def get_approver_name(self, obj):
        if obj.approver:
            return f"{obj.approver.first_name} {obj.approver.last_name}".strip()
        return "Not Assigned"


class ApprovalRequestSerializer(serializers.ModelSerializer):
    requester_detail = UserSerializer(source='requester', read_only=True)
    workflow_detail = ApprovalWorkflowSerializer(source='workflow', read_only=True)
    content_type_detail = ContentTypeSerializer(source='content_type', read_only=True)
    current_step_detail = ApprovalStepSerializer(source='current_step', read_only=True)
    current_status_display = serializers.SerializerMethodField()
    is_complete = serializers.SerializerMethodField()
    pending_approvals_count = serializers.SerializerMethodField()

    class Meta:
        model = ApprovalRequest
        fields = [
            'id', 'workflow', 'workflow_detail', 'requester', 'requester_detail',
            'content_type', 'content_type_detail', 'object_id', 'title', 'description',
            'status', 'current_status_display', 'is_complete', 'current_step',
            'current_step_detail', 'urgency', 'amount', 'currency',
            'pending_approvals_count', 'submitted_at', 'approved_at', 'rejected_at',
            'cancelled_at', 'created_at', 'updated_at'
        ]
        read_only_fields = ['submitted_at', 'approved_at', 'rejected_at',
                           'cancelled_at', 'created_at', 'updated_at']

    def get_current_status_display(self, obj):
        if obj.status in ['submitted', 'in_progress']:
            pending_count = Approval.objects.filter(
                content_type=obj.content_type,
                object_id=obj.object_id,
                status='pending'
            ).count()
            total_count = obj.workflow.steps.count() if obj.workflow else 0
            approved_count = total_count - pending_count
            return f"Pending ({approved_count}/{total_count} approved)"
        return obj.get_status_display()

    def get_is_complete(self, obj):
        return obj.status in ['approved', 'rejected', 'cancelled']

    def get_pending_approvals_count(self, obj):
        return Approval.objects.filter(
            content_type=obj.content_type,
            object_id=obj.object_id,
            status='pending'
        ).count()


class ApprovalRequestListSerializer(serializers.ModelSerializer):
    """Simplified serializer for list views"""
    requester_detail = UserSerializer(source='requester', read_only=True)
    workflow_name = serializers.CharField(source='workflow.name', read_only=True)
    workflow_type = serializers.CharField(source='workflow.workflow_type', read_only=True)

    class Meta:
        model = ApprovalRequest
        fields = [
            'id', 'workflow', 'workflow_name', 'workflow_type', 'requester',
            'requester_detail', 'title', 'status', 'urgency', 'amount',
            'submitted_at', 'created_at'
        ]
