from rest_framework import viewsets, permissions, filters, status
from rest_framework.decorators import action
from rest_framework.response import Response
from .models import PipelineStage, Deal
from .serializers import PipelineStageSerializer, DealSerializer


class PipelineStageViewSet(viewsets.ModelViewSet):
    queryset = PipelineStage.objects.all()
    serializer_class = PipelineStageSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.OrderingFilter]
    ordering_fields = ['order']
    throttle_scope = 'user'


class DealViewSet(viewsets.ModelViewSet):
    queryset = Deal.objects.all()
    serializer_class = DealSerializer
    permission_classes = [permissions.IsAuthenticated]
    filter_backends = [filters.SearchFilter, filters.OrderingFilter]
    search_fields = ['title', 'contact__user__first_name', 'contact__user__last_name']
    ordering_fields = ['created_at', 'amount', 'close_date']
    throttle_scope = 'user'

    @action(detail=True, methods=['post'], url_path='move')
    def move(self, request, pk=None):
        deal = self.get_object()
        stage_id = request.data.get('stage')
        if not stage_id:
            return Response({'detail': 'stage is required'}, status=status.HTTP_400_BAD_REQUEST)
        try:
            stage = PipelineStage.objects.get(pk=stage_id)
        except PipelineStage.DoesNotExist:
            return Response({'detail': 'Stage not found'}, status=status.HTTP_404_NOT_FOUND)
        deal.stage = stage
        deal.save(update_fields=['stage'])
        return Response(self.get_serializer(deal).data)


class OpportunityViewSet(DealViewSet):
    def get_queryset(self):
        qs = super().get_queryset()
        # Opportunities: deals not in won/lost stages
        return qs.filter(stage__is_won=False, stage__is_lost=False)


