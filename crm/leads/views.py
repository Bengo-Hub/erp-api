from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import Lead
from .serializers import LeadSerializer
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
import logging

logger = logging.getLogger(__name__)


class LeadViewSet(BaseModelViewSet):
    queryset = Lead.objects.all().select_related('contact__user')
    serializer_class = LeadSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['contact__user__first_name', 'contact__user__last_name', 'source']
    ordering_fields = ['created_at', 'value']
    throttle_scope = 'user'

    @action(detail=True, methods=['post'], url_path='advance')
    def advance(self, request, pk=None):
        """Advance lead to next status in pipeline."""
        try:
            correlation_id = get_correlation_id(request)
            lead = self.get_object()
            
            transitions = {
                'new': 'contacted',
                'contacted': 'qualified',
                'qualified': 'won',
            }
            next_status = transitions.get(lead.status)
            
            if not next_status:
                return APIResponse.bad_request(
                    message='Cannot advance lead from current status',
                    error_id='invalid_status_transition',
                    correlation_id=correlation_id
                )
            
            old_status = lead.status
            lead.status = next_status
            lead.save(update_fields=['status', 'updated_at'])
            
            # Log status change
            AuditTrail.log(
                operation=AuditTrail.UPDATE,
                module='crm',
                entity_type='Lead',
                entity_id=lead.id,
                user=request.user,
                changes={'status': {'old': old_status, 'new': next_status}},
                reason=f'Lead advanced from {old_status} to {next_status}',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(lead).data,
                message='Lead advanced successfully',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error advancing lead: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error advancing lead',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )

    @action(detail=True, methods=['post'], url_path='lose')
    def lose(self, request, pk=None):
        """Mark lead as lost."""
        try:
            correlation_id = get_correlation_id(request)
            lead = self.get_object()
            
            old_status = lead.status
            lead.status = 'lost'
            lead.save(update_fields=['status', 'updated_at'])
            
            # Log status change
            AuditTrail.log(
                operation=AuditTrail.UPDATE,
                module='crm',
                entity_type='Lead',
                entity_id=lead.id,
                user=request.user,
                changes={'status': {'old': old_status, 'new': 'lost'}},
                reason='Lead marked as lost',
                request=request
            )
            
            return APIResponse.success(
                data=self.get_serializer(lead).data,
                message='Lead marked as lost',
                correlation_id=correlation_id
            )
        except Exception as e:
            logger.error(f'Error marking lead as lost: {str(e)}', exc_info=True)
            return APIResponse.server_error(
                message='Error marking lead as lost',
                error_id=str(e),
                correlation_id=get_correlation_id(request)
            )


