from django.shortcuts import render
from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from rest_framework.pagination import LimitOffsetPagination
from django_filters import rest_framework as filters
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType
from .models import ApprovalWorkflow, ApprovalStep, Approval, ApprovalRequest
from .serializers import (
    ApprovalWorkflowSerializer, ApprovalWorkflowListSerializer,
    ApprovalStepSerializer, ApprovalSerializer, ApprovalRequestSerializer,
    ApprovalRequestListSerializer
)
from django.contrib.auth import get_user_model
from django.db import models


# Create your views here.


class ApprovalWorkflowFilter(filters.FilterSet):
    """Filter for ApprovalWorkflow"""
    name = filters.CharFilter(lookup_expr='icontains')
    content_type = filters.ModelChoiceFilter(queryset=ContentType.objects.all())
    is_active = filters.BooleanFilter()
    
    class Meta:
        model = ApprovalWorkflow
        fields = ['name', 'content_type', 'is_active']


class ApprovalWorkflowViewSet(viewsets.ModelViewSet):
    """ViewSet for ApprovalWorkflow model"""
    queryset = ApprovalWorkflow.objects.all()
    serializer_class = ApprovalWorkflowSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = ApprovalWorkflowFilter
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ApprovalWorkflowListSerializer
        return ApprovalWorkflowSerializer
    
    def get_queryset(self):
        return super().get_queryset().select_related('content_type').prefetch_related('steps')
    
    @action(detail=True, methods=['post'])
    def activate(self, request, pk=None):
        """Activate a workflow"""
        workflow = self.get_object()
        workflow.is_active = True
        workflow.save()
        return Response({'status': 'Workflow activated'})
    
    @action(detail=True, methods=['post'])
    def deactivate(self, request, pk=None):
        """Deactivate a workflow"""
        workflow = self.get_object()
        workflow.is_active = False
        workflow.save()
        return Response({'status': 'Workflow deactivated'})
    
    @action(detail=False, methods=['get'], url_path='content-types')
    def content_types(self, request):
        """Get available content types for approval workflows"""
        content_types = ContentType.objects.all().order_by('app_label', 'model')
        data = []
        for ct in content_types:
            data.append({
                'id': ct.id,
                'app_label': ct.app_label,
                'model': ct.model,
                'name': ct.name
            })
        return Response(data)


class ApprovalStepViewSet(viewsets.ModelViewSet):
    """ViewSet for ApprovalStep model"""
    queryset = ApprovalStep.objects.all()
    serializer_class = ApprovalStepSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    
    def get_queryset(self):
        return super().get_queryset().select_related('workflow', 'approver')
    
    def perform_create(self, serializer):
        # Ensure step numbers are sequential
        workflow = serializer.validated_data['workflow']
        max_step = workflow.steps.aggregate(max_step=models.Max('step_number'))['max_step'] or 0
        serializer.save(step_number=max_step + 1)


class ApprovalFilter(filters.FilterSet):
    """Filter for Approval"""
    status = filters.CharFilter(lookup_expr='icontains')
    approver = filters.ModelChoiceFilter(queryset=get_user_model().objects.all())
    workflow = filters.ModelChoiceFilter(queryset=ApprovalWorkflow.objects.all())
    content_type = filters.ModelChoiceFilter(queryset=ContentType.objects.all())
    
    class Meta:
        model = Approval
        fields = ['status', 'approver', 'workflow', 'content_type']


class ApprovalViewSet(viewsets.ModelViewSet):
    """ViewSet for Approval model"""
    queryset = Approval.objects.all()
    serializer_class = ApprovalSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = ApprovalFilter
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # If user is not superuser, only show their approvals
        if not user.is_superuser:
            queryset = queryset.filter(approver=user)
        
        return queryset.select_related('workflow', 'step', 'approver', 'content_type')
    
    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve an approval request"""
        approval = self.get_object()
        
        if approval.status != 'pending':
            return Response(
                {'error': 'Approval is not in pending status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        approval.status = 'approved'
        approval.notes = request.data.get('notes', '')
        approval.save()
        
        # Check if all approvals in the request are complete
        request_obj = approval.approval_request
        if request_obj:
            pending_approvals = request_obj.approvals.filter(status='pending').count()
            if pending_approvals == 0:
                request_obj.status = 'approved'
                request_obj.save()
        
        return Response({'status': 'Approval granted'})
    
    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject an approval request"""
        approval = self.get_object()
        
        if approval.status != 'pending':
            return Response(
                {'error': 'Approval is not in pending status'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        approval.status = 'rejected'
        approval.notes = request.data.get('notes', '')
        approval.save()
        
        # Mark the entire request as rejected
        request_obj = approval.approval_request
        if request_obj:
            request_obj.status = 'rejected'
            request_obj.save()
        
        return Response({'status': 'Approval rejected'})


class ApprovalRequestFilter(filters.FilterSet):
    """Filter for ApprovalRequest"""
    status = filters.CharFilter(lookup_expr='icontains')
    requester = filters.ModelChoiceFilter(queryset=get_user_model().objects.all())
    workflow = filters.ModelChoiceFilter(queryset=ApprovalWorkflow.objects.all())
    content_type = filters.ModelChoiceFilter(queryset=ContentType.objects.all())
    
    class Meta:
        model = ApprovalRequest
        fields = ['status', 'requester', 'workflow', 'content_type']


class ApprovalRequestViewSet(viewsets.ModelViewSet):
    """ViewSet for ApprovalRequest model"""
    queryset = ApprovalRequest.objects.all()
    serializer_class = ApprovalRequestSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = LimitOffsetPagination
    filter_backends = [filters.DjangoFilterBackend]
    filterset_class = ApprovalRequestFilter
    
    def get_serializer_class(self):
        if self.action == 'list':
            return ApprovalRequestListSerializer
        return ApprovalRequestSerializer
    
    def get_queryset(self):
        queryset = super().get_queryset()
        user = self.request.user
        
        # If user is not superuser, only show their requests or approvals they can make
        if not user.is_superuser:
            queryset = queryset.filter(
                Q(requester=user) | Q(approvals__approver=user)
            ).distinct()
        
        return queryset.select_related('workflow', 'requester', 'content_type').prefetch_related('approvals')
    
    def perform_create(self, serializer):
        request_obj = serializer.save(requester=self.request.user)
        
        # Create approval instances for each step in the workflow
        workflow = request_obj.workflow
        for step in workflow.steps.all():
            Approval.objects.create(
                workflow=workflow,
                step=step,
                approval_request=request_obj,
                approver=step.approver,
                content_type=request_obj.content_type,
                object_id=request_obj.object_id,
                status='pending'
            )
    
    @action(detail=True, methods=['post'])
    def cancel(self, request, pk=None):
        """Cancel an approval request"""
        request_obj = self.get_object()
        
        if request_obj.status != 'pending':
            return Response(
                {'error': 'Request cannot be cancelled in its current state'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        request_obj.status = 'cancelled'
        request_obj.save()
        
        # Cancel all pending approvals
        request_obj.approvals.filter(status='pending').update(status='cancelled')
        
        return Response({'status': 'Request cancelled'})
    
    @action(detail=False, methods=['get'])
    def my_pending_approvals(self, request):
        """Get pending approvals for the current user"""
        user = request.user
        pending_approvals = Approval.objects.filter(
            approver=user,
            status='pending'
        ).select_related('workflow', 'approval_request', 'content_type')
        
        serializer = ApprovalSerializer(pending_approvals, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=['get'])
    def audit(self, request, pk=None):
        """Return audit-style view of an approval request with steps and statuses."""
        request_obj = self.get_object()
        approvals = request_obj.approvals.select_related('step', 'approver').all()
        data = {
            'id': request_obj.id,
            'workflow': getattr(request_obj.workflow, 'name', None),
            'status': request_obj.status,
            'requested_by': getattr(request_obj.requester, 'id', None),
            'requested_at': request_obj.created_at,
            'approvals': [
                {
                    'step': a.step.name if a.step else None,
                    'step_number': a.step.step_number if a.step else None,
                    'approver_id': a.approver_id,
                    'status': a.status,
                    'notes': a.notes,
                    'approved_at': a.approved_at,
                    'rejected_at': a.rejected_at,
                    'delegated_to': a.delegated_to_id,
                }
                for a in approvals
            ]
        }
        return Response(data)