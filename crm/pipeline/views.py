from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import PipelineStage, Deal
from .serializers import PipelineStageSerializer, DealSerializer
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from django.db import transaction
import logging

logger = logging.getLogger(__name__)


class PipelineStageViewSet(BaseModelViewSet):
    queryset = PipelineStage.objects.all()
    serializer_class = PipelineStageSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['order']
    throttle_scope = 'user'


class DealViewSet(BaseModelViewSet):
    queryset = Deal.objects.all().select_related('contact__user', 'stage')
    serializer_class = DealSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'contact__user__first_name', 'contact__user__last_name']
    ordering_fields = ['created_at', 'amount', 'close_date']
    throttle_scope = 'user'

    @action(detail=True, methods=['post'], url_path='move')
    def move(self, request, pk=None):
        """Move deal to a different pipeline stage"""
        try:
            correlation_id = get_correlation_id(request)
            deal = self.get_object()
            stage_id = request.data.get('stage')
            if not stage_id:
                return APIResponse.bad_request(message='Stage is required', error_id='missing_stage', correlation_id=correlation_id)
            try:
                stage = PipelineStage.objects.get(pk=stage_id)
            except PipelineStage.DoesNotExist:
                return APIResponse.not_found(message='Stage not found', correlation_id=correlation_id)
            
            old_stage = deal.stage
            deal.stage = stage
            deal.save(update_fields=['stage', 'updated_at'])
            AuditTrail.log(operation=AuditTrail.UPDATE, module='crm', entity_type='Deal', entity_id=deal.id, user=request.user, changes={'stage': {'old': old_stage.id if old_stage else None, 'new': stage.id}}, reason=f'Deal moved to {stage.name}', request=request)
            return APIResponse.success(data=self.get_serializer(deal).data, message='Deal moved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error moving deal: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error moving deal', error_id=str(e), correlation_id=get_correlation_id(request))


class OpportunityViewSet(DealViewSet):
    def get_queryset(self):
        qs = super().get_queryset()
        # Opportunities: deals not in won/lost stages
        return qs.filter(stage__is_won=False, stage__is_lost=False)


