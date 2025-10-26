from rest_framework import viewsets, status, permissions
from rest_framework.response import Response
from rest_framework.decorators import action
from .models import ProcurementRequest
from .serializers import ProcurementRequestSerializer
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class ProcurementRequestViewSet(BaseModelViewSet):
    """
    API endpoint that allows procurement requests to be viewed or edited.
    """
    serializer_class = ProcurementRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        """Optimize queries with select_related for related objects."""
        queryset = ProcurementRequest.objects.all().select_related('requester', 'approved_by')
        
        # Filter by query parameters
        requester = self.request.query_params.get('requester', None)
        status_filter = self.request.query_params.get('status', None)
        request_type = self.request.query_params.get('request_type', None)
        
        if requester:
            queryset = queryset.filter(requester=requester)
        if status_filter:
            queryset = queryset.filter(status=status_filter)
        if request_type:
            queryset = queryset.filter(request_type=request_type)
            
        return queryset

    def perform_create(self, serializer):
        serializer.save(requester=self.request.user)

    @action(detail=True, methods=['post'])
    def approve(self, request, pk=None):
        """Approve a procurement request."""
        try:
            correlation_id = get_correlation_id(request)
            procurement_request = self.get_object()
            
            # Create approval record
            procurement_request.approvals.create(
                approver=request.user,
                status='approved',
                notes=request.data.get('notes', 'Approved by ' + request.user.username)
            )
            
            # Update request status
            procurement_request.status = 'approved'
            procurement_request.save()
            
            # Log approval
            AuditTrail.log(
                operation=AuditTrail.APPROVAL,
                module='procurement',
                entity_type='ProcurementRequest',
                entity_id=procurement_request.id,
                user=request.user,
                reason='Procurement request approved',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(procurement_request).data,
                message='Procurement request approved successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error approving procurement request: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error approving procurement request',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )
    
    @action(detail=True, methods=['post'])
    def publish(self, request, pk=None):
        """Publish a procurement request for approval workflow."""
        try:
            correlation_id = get_correlation_id(request)
            procurement_request = self.get_object()
            
            # Create approval record
            procurement_request.request_approvals.create(
                approver=request.user,
                status='pending',
                notes=request.data.get('notes', 'Published by ' + request.user.username)
            )
            
            # Update request status
            procurement_request.status = 'submitted'
            procurement_request.save()
            
            # Log publication
            AuditTrail.log(
                operation=AuditTrail.SUBMIT,
                module='procurement',
                entity_type='ProcurementRequest',
                entity_id=procurement_request.id,
                user=request.user,
                reason='Procurement request published',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(procurement_request).data,
                message='Procurement request published successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error publishing procurement request: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error publishing procurement request',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'])
    def reject(self, request, pk=None):
        """Reject a procurement request."""
        try:
            correlation_id = get_correlation_id(request)
            procurement_request = self.get_object()
            
            # Create rejection record
            procurement_request.request_approvals.create(
                approver=request.user,
                status='rejected',
                notes=request.data.get('notes', 'Rejected by ' + request.user.username)
            )
            
            # Update request status
            procurement_request.status = 'rejected'
            procurement_request.save()
            
            # Log rejection
            AuditTrail.log(
                operation=AuditTrail.CANCEL,
                module='procurement',
                entity_type='ProcurementRequest',
                entity_id=procurement_request.id,
                user=request.user,
                reason='Procurement request rejected',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(procurement_request).data,
                message='Procurement request rejected',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error rejecting procurement request: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error rejecting procurement request',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'])
    def process(self, request, pk=None):
        """
        Process approved requests based on their type
        """
        procurement_request = self.get_object()
        
        if procurement_request.status != 'approved':
            return Response(
                {'error': 'Only approved requests can be processed'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Add processing logic here based on request_type
        procurement_request.status = 'processing'
        procurement_request.save()
        return Response({'status': 'processing'})

class UserRequestViewSet(viewsets.ModelViewSet):
    """
    API endpoint that shows requests for the current user only
    """
    serializer_class = ProcurementRequestSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return ProcurementRequest.objects.filter(requester=self.request.user)

    def perform_create(self, serializer):
        serializer.save(requester=self.request.user)
