from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated, IsAuthenticatedOrReadOnly
from rest_framework.pagination import LimitOffsetPagination
from django.utils import timezone
from django.db.models import Q
from .models import Campaign, CampaignPerformance
from .serializers import (
    CampaignSerializer, CampaignListSerializer, CampaignCreateSerializer,
    CampaignUpdateSerializer, CampaignPerformanceSerializer
)
from core.base_viewsets import BaseModelViewSet
from core.response import APIResponse, get_correlation_id
from core.audit import AuditTrail
from django.db import transaction
import logging

logger = logging.getLogger(__name__)


class CampaignViewSet(BaseModelViewSet):
    """ViewSet for Campaign management"""
    
    queryset = Campaign.objects.all()
    serializer_class = CampaignSerializer
    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = LimitOffsetPagination
    
    def get_serializer_class(self):
        if self.action == 'create':
            return CampaignCreateSerializer
        elif self.action in ['update', 'partial_update']:
            return CampaignUpdateSerializer
        elif self.action == 'list':
            return CampaignListSerializer
        return CampaignSerializer
    
    @action(detail=False, methods=['get'])
    def active_banners(self, request):
        """Get active banner campaigns for display"""
        try:
            correlation_id = get_correlation_id(request)
            now = timezone.now()
            
            # Get active banner campaigns
            active_banners = Campaign.objects.filter(
                campaign_type='banner',
                status='active',
                is_active=True,
                start_date__lte=now,
                end_date__gte=now
            ).order_by('priority')[:5]
            
            # If no active banners, get default ones
            if not active_banners.exists():
                active_banners = Campaign.objects.filter(
                    campaign_type='banner',
                    is_active=True,
                    is_default=True
                ).order_by('?')[:3]
            
            serializer = CampaignListSerializer(active_banners, many=True)
            return APIResponse.success(data=serializer.data, message='Active banners retrieved successfully', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error fetching active banners: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error retrieving active banners', error_id=str(e), correlation_id=get_correlation_id(request))


class CampaignPerformanceViewSet(BaseModelViewSet):
    """ViewSet for CampaignPerformance tracking"""
    
    queryset = CampaignPerformance.objects.all().select_related('campaign')
    serializer_class = CampaignPerformanceSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = LimitOffsetPagination
    
    def get_queryset(self):
        """Filter performance data by campaign and date range"""
        queryset = super().get_queryset()
        
        campaign_id = self.request.query_params.get('campaign')
        if campaign_id:
            queryset = queryset.filter(campaign_id=campaign_id)
        
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date and end_date:
            queryset = queryset.filter(date__range=[start_date, end_date])
        
        return queryset
    
    @action(detail=False, methods=['post'])
    def bulk_update(self, request):
        """Bulk update campaign performance metrics"""
        try:
            correlation_id = get_correlation_id(request)
            performance_data = request.data.get('performance_data', [])
            
            if not performance_data:
                return APIResponse.bad_request(message='performance_data is required', error_id='missing_performance_data', correlation_id=correlation_id)
            
            updated_records = []
            with transaction.atomic():
                for data in performance_data:
                    campaign_id = data.get('campaign_id')
                    date = data.get('date')
                    impressions = data.get('impressions', 0)
                    clicks = data.get('clicks', 0)
                    conversions = data.get('conversions', 0)
                    revenue = data.get('revenue', 0)
                    
                    if campaign_id and date:
                        performance, created = CampaignPerformance.objects.get_or_create(
                            campaign_id=campaign_id,
                            date=date,
                            defaults={
                                'impressions': impressions,
                                'clicks': clicks,
                                'conversions': conversions,
                                'revenue': revenue
                            }
                        )
                        
                        if not created:
                            performance.impressions = impressions
                            performance.clicks = clicks
                            performance.conversions = conversions
                            performance.revenue = revenue
                            performance.save()
                        
                        updated_records.append(performance)
                        AuditTrail.log(operation=AuditTrail.UPDATE, module='crm', entity_type='CampaignPerformance', entity_id=performance.id, user=request.user, reason='Updated campaign performance metrics', request=request)
            
            serializer = self.get_serializer(updated_records, many=True)
            return APIResponse.success(data={'message': f'Updated {len(updated_records)} performance records', 'data': serializer.data}, message='Performance metrics updated', correlation_id=correlation_id)
        except Exception as e:
            logger.error(f'Error bulk updating campaign performance: {str(e)}', exc_info=True)
            return APIResponse.server_error(message='Error updating performance', error_id=str(e), correlation_id=get_correlation_id(request))
