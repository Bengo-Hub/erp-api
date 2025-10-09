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


class CampaignViewSet(viewsets.ModelViewSet):
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
        return Response(serializer.data)


class CampaignPerformanceViewSet(viewsets.ModelViewSet):
    """ViewSet for CampaignPerformance tracking"""
    
    queryset = CampaignPerformance.objects.all()
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
        
        return queryset.select_related('campaign')
    
    @action(detail=False, methods=['post'])
    def bulk_update(self, request):
        """Bulk update campaign performance metrics"""
        performance_data = request.data.get('performance_data', [])
        
        updated_records = []
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
        
        serializer = self.get_serializer(updated_records, many=True)
        return Response({
            'message': f'Updated {len(updated_records)} performance records',
            'data': serializer.data
        })
