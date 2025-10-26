from django.shortcuts import render
from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Contract, ContractOrderLink
from .serializers import ContractSerializer, ContractOrderLinkSerializer
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class ContractViewSet(BaseModelViewSet):
    queryset = Contract.objects.all().select_related('supplier')
    serializer_class = ContractSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'supplier__user__first_name', 'supplier__user__last_name']
    ordering_fields = ['start_date', 'end_date', 'value', 'created_at']

    @action(detail=True, methods=['post'], url_path='activate')
    def activate(self, request, pk=None):
        """Activate a contract."""
        try:
            correlation_id = get_correlation_id(request)
            contract = self.get_object()
            
            old_status = contract.status
            contract.status = 'active'
            contract.save(update_fields=['status', 'updated_at'])
            
            # Log activation
            AuditTrail.log(
                operation=AuditTrail.UPDATE,
                module='procurement',
                entity_type='Contract',
                entity_id=contract.id,
                user=request.user,
                changes={'status': {'old': old_status, 'new': 'active'}},
                reason=f'Contract {contract.title} activated',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(contract).data,
                message='Contract activated successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error activating contract: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error activating contract',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='terminate')
    def terminate(self, request, pk=None):
        """Terminate a contract."""
        try:
            correlation_id = get_correlation_id(request)
            contract = self.get_object()
            
            old_status = contract.status
            contract.status = 'terminated'
            contract.save(update_fields=['status', 'updated_at'])
            
            # Log termination
            AuditTrail.log(
                operation=AuditTrail.CANCEL,
                module='procurement',
                entity_type='Contract',
                entity_id=contract.id,
                user=request.user,
                changes={'status': {'old': old_status, 'new': 'terminated'}},
                reason=f'Contract {contract.title} terminated',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(contract).data,
                message='Contract terminated successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error terminating contract: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error terminating contract',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )


class ContractOrderLinkViewSet(BaseModelViewSet):
    queryset = ContractOrderLink.objects.all().select_related('contract', 'order')
    serializer_class = ContractOrderLinkSerializer
    permission_classes = [permissions.IsAuthenticated]
