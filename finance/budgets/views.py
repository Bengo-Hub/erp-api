from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Budget, BudgetLine
from .serializers import BudgetSerializer, BudgetLineSerializer
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from django.db import transaction
import logging

logger = logging.getLogger(__name__)


class BudgetViewSet(BaseModelViewSet):
    queryset = Budget.objects.all().select_related('created_by')
    serializer_class = BudgetSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name']
    ordering_fields = ['start_date', 'end_date', 'created_at']
    throttle_scope = 'user'

    def perform_create(self, serializer):
        serializer.save(created_by=self.request.user)

    @action(detail=True, methods=['post'], url_path='approve')
    def approve(self, request, pk=None):
        """Approve a budget"""
        try:
            correlation_id = get_correlation_id(request)
            budget = self.get_object()
            old_status = budget.status
            budget.status = 'approved'
            budget.save(update_fields=['status', 'updated_at'])
            AuditTrail.log(operation=AuditTrail.APPROVAL, module='finance', entity_type='Budget', entity_id=budget.id, user=request.user, changes={'status': {'old': old_status, 'new': 'approved'}}, reason='Budget approved', request=request)
            return APIResponse.success(data=self.get_serializer(budget).data, message='Budget approved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error approving budget: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error approving budget', error_id=str(e), correlation_id=get_correlation_id(request))

    @action(detail=True, methods=['post'], url_path='reject')
    def reject(self, request, pk=None):
        """Reject a budget"""
        try:
            correlation_id = get_correlation_id(request)
            budget = self.get_object()
            old_status = budget.status
            budget.status = 'rejected'
            budget.save(update_fields=['status', 'updated_at'])
            AuditTrail.log(operation=AuditTrail.CANCEL, module='finance', entity_type='Budget', entity_id=budget.id, user=request.user, changes={'status': {'old': old_status, 'new': 'rejected'}}, reason='Budget rejected', request=request)
            return APIResponse.success(data=self.get_serializer(budget).data, message='Budget rejected successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error rejecting budget: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error rejecting budget', error_id=str(e), correlation_id=get_correlation_id(request))


class BudgetLineViewSet(BaseModelViewSet):
    queryset = BudgetLine.objects.all().select_related('budget')
    serializer_class = BudgetLineSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['name', 'category']
    ordering_fields = ['amount']
    throttle_scope = 'user'
