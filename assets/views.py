from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django_filters.rest_framework import DjangoFilterBackend
from django.db.models import Q, Count, Sum
from django.utils import timezone
from decimal import Decimal
import polars as pl
from datetime import timedelta
from django.db.models.functions import TruncMonth
from .models import (
    AssetCategory, Asset, AssetDepreciation,
    AssetInsurance, AssetAudit, AssetReservation, AssetTransfer,
    AssetMaintenance, AssetDisposal
)
from .serializers import (
    AssetCategorySerializer, AssetSerializer,
    AssetDepreciationSerializer, AssetInsuranceSerializer, AssetAuditSerializer,
    AssetReservationSerializer, AssetTransferSerializer, AssetMaintenanceSerializer,
    AssetDisposalSerializer
)

class AssetCategoryViewSet(viewsets.ModelViewSet):
    queryset = AssetCategory.objects.filter(is_active=True)
    serializer_class = AssetCategorySerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['is_active', 'parent']

class AssetViewSet(viewsets.ModelViewSet):
    queryset = Asset.objects.filter(is_active=True)
    serializer_class = AssetSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['category', 'status', 'branch', 'assigned_to', 'custodian', 'condition']

    def get_queryset(self):
        queryset = Asset.objects.filter(is_active=True)
        search = self.request.query_params.get('search', None)
        if search:
            queryset = queryset.filter(
                Q(asset_tag__icontains=search) |
                Q(name__icontains=search) |
                Q(serial_number__icontains=search) |
                Q(model__icontains=search) |
                Q(manufacturer__icontains=search)
            )
        return queryset

    @action(detail=True, methods=['post'])
    def transfer(self, request, pk=None):
        """Transfer asset to new location/user"""
        asset = self.get_object()
        serializer = AssetTransferSerializer(data=request.data)
        if serializer.is_valid():
            transfer = serializer.save(asset=asset, transferred_by=request.user)
            return Response(AssetTransferSerializer(transfer).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def schedule_maintenance(self, request, pk=None):
        """Schedule maintenance for asset"""
        asset = self.get_object()
        serializer = AssetMaintenanceSerializer(data=request.data)
        if serializer.is_valid():
            maintenance = serializer.save(asset=asset)
            return Response(AssetMaintenanceSerializer(maintenance).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['post'])
    def dispose(self, request, pk=None):
        """Dispose of asset"""
        asset = self.get_object()
        serializer = AssetDisposalSerializer(data=request.data)
        if serializer.is_valid():
            disposal = serializer.save(asset=asset, approved_by=request.user)
            # Update asset status to disposed
            asset.status = 'disposed'
            asset.current_value = Decimal('0.00')
            asset.save()
            return Response(AssetDisposalSerializer(disposal).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    @action(detail=True, methods=['get'])
    def depreciation_schedule(self, request, pk=None):
        """Get depreciation schedule for asset"""
        asset = self.get_object()
        years = int(request.query_params.get('years', asset.category.useful_life_years if asset.category else 5))
        schedule = asset.get_depreciation_schedule(years)
        return Response(schedule)

    @action(detail=True, methods=['post'])
    def record_depreciation(self, request, pk=None):
        """Record depreciation for asset"""
        asset = self.get_object()
        serializer = AssetDepreciationSerializer(data=request.data)
        if serializer.is_valid():
            depreciation = serializer.save(asset=asset)
            # Update asset accumulated depreciation
            asset.accumulated_depreciation = Decimal(str(asset.accumulated_depreciation)) + depreciation.depreciation_amount
            asset.current_value = Decimal(str(asset.current_value)) - depreciation.depreciation_amount
            asset.save()
            return Response(AssetDepreciationSerializer(depreciation).data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

class AssetDepreciationViewSet(viewsets.ModelViewSet):
    queryset = AssetDepreciation.objects.all()
    serializer_class = AssetDepreciationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['asset', 'posted_to_finance', 'period_start']

class AssetInsuranceViewSet(viewsets.ModelViewSet):
    queryset = AssetInsurance.objects.filter(is_active=True)
    serializer_class = AssetInsuranceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['asset', 'provider', 'is_active', 'start_date']

class AssetAuditViewSet(viewsets.ModelViewSet):
    queryset = AssetAudit.objects.all()
    serializer_class = AssetAuditSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['asset', 'auditor', 'status', 'audit_date']

class AssetReservationViewSet(viewsets.ModelViewSet):
    queryset = AssetReservation.objects.all()
    serializer_class = AssetReservationSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['asset', 'reserved_by', 'status', 'start_date']

class AssetTransferViewSet(viewsets.ModelViewSet):
    queryset = AssetTransfer.objects.all()
    serializer_class = AssetTransferSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['asset', 'transferred_by', 'status', 'transfer_date']

class AssetMaintenanceViewSet(viewsets.ModelViewSet):
    queryset = AssetMaintenance.objects.all()
    serializer_class = AssetMaintenanceSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['asset', 'maintenance_type', 'status', 'scheduled_date']

    @action(detail=True, methods=['post'])
    def complete(self, request, pk=None):
        """Mark maintenance as completed"""
        maintenance = self.get_object()
        maintenance.status = 'completed'
        maintenance.completed_date = request.data.get('completed_date')
        maintenance.save()
        serializer = self.get_serializer(maintenance)
        return Response(serializer.data)

class AssetDisposalViewSet(viewsets.ModelViewSet):
    queryset = AssetDisposal.objects.all()
    serializer_class = AssetDisposalSerializer
    permission_classes = [IsAuthenticated]
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['asset', 'disposal_method', 'approved_by', 'status', 'disposal_date']


class AssetDashboardViewSet(viewsets.ViewSet):
    """Dashboard analytics for assets using Polars for high-performance data processing"""
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        """Get comprehensive asset dashboard analytics"""
        try:
            # Get date range for analytics (last 12 months)
            end_date = timezone.now()
            start_date = end_date - timedelta(days=365)

            # Asset overview statistics
            total_assets = Asset.objects.filter(is_active=True).count()
            active_assets = Asset.objects.filter(is_active=True, status='active').count()
            inactive_assets = Asset.objects.filter(is_active=True, status='inactive').count()
            maintenance_assets = Asset.objects.filter(is_active=True, status='maintenance').count()
            disposed_assets = Asset.objects.filter(status='disposed').count()

            # Category distribution using Polars
            category_stats = self._get_category_analytics()

            # Asset value analytics
            total_purchase_value = Asset.objects.filter(is_active=True).aggregate(
                total=Sum('purchase_cost')
            )['total'] or 0

            total_current_value = Asset.objects.filter(is_active=True).aggregate(
                total=Sum('current_value')
            )['total'] or 0

            total_accumulated_depreciation = Asset.objects.filter(is_active=True).aggregate(
                total=Sum('accumulated_depreciation')
            )['total'] or 0

            # Monthly trends using Polars
            monthly_trends = self._get_monthly_trends(start_date, end_date)

            # Recent activities
            recent_transfers = AssetTransfer.objects.filter(
                transfer_date__gte=start_date
            ).order_by('-transfer_date')[:10]

            recent_maintenance = AssetMaintenance.objects.filter(
                scheduled_date__gte=start_date,
                status='completed'
            ).order_by('-completed_date')[:10]

            recent_disposals = AssetDisposal.objects.filter(
                disposal_date__gte=start_date
            ).order_by('-disposal_date')[:10]

            # Insurance expiry warnings
            insurance_warnings = AssetInsurance.objects.filter(
                is_active=True,
                end_date__lte=end_date + timedelta(days=30),
                end_date__gte=end_date
            ).count()

            # Maintenance due soon
            maintenance_due = AssetMaintenance.objects.filter(
                status='scheduled',
                scheduled_date__lte=end_date + timedelta(days=7)
            ).count()

            dashboard_data = {
                'overview': {
                    'total_assets': total_assets,
                    'active_assets': active_assets,
                    'inactive_assets': inactive_assets,
                    'maintenance_assets': maintenance_assets,
                    'disposed_assets': disposed_assets,
                },
                'value_analytics': {
                    'total_purchase_value': float(total_purchase_value),
                    'total_current_value': float(total_current_value),
                    'total_accumulated_depreciation': float(total_accumulated_depreciation),
                    'depreciation_rate': float((total_accumulated_depreciation / total_purchase_value * 100) if total_purchase_value > 0 else 0),
                },
                'category_distribution': category_stats,
                'monthly_trends': monthly_trends,
                'recent_activities': {
                    'transfers': AssetTransferSerializer(recent_transfers, many=True).data,
                    'maintenance': AssetMaintenanceSerializer(recent_maintenance, many=True).data,
                    'disposals': AssetDisposalSerializer(recent_disposals, many=True).data,
                },
                'alerts': {
                    'insurance_expiring_soon': insurance_warnings,
                    'maintenance_due_soon': maintenance_due,
                },
                'generated_at': timezone.now().isoformat(),
            }

            return Response(dashboard_data)

        except Exception as e:
            return Response(
                {'error': f'Failed to generate dashboard analytics: {str(e)}'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )

    def _get_category_analytics(self):
        """Get asset distribution by category using Polars"""
        # Get category data using Django ORM
        categories = AssetCategory.objects.filter(is_active=True).annotate(
            asset_count=Count('assets'),
            total_value=Sum('assets__current_value')
        ).values('id', 'name', 'asset_count', 'total_value')

        # Convert to list for Polars processing
        category_data = list(categories)

        if not category_data:
            return []

        # Use Polars for advanced analytics
        df = pl.DataFrame(category_data)

        # Calculate percentages and other metrics
        total_assets = df['asset_count'].sum()
        total_value = df['total_value'].sum()

        result = df.with_columns([
            (pl.col('asset_count') / total_assets * 100).alias('percentage'),
            (pl.col('total_value') / total_value * 100).alias('value_percentage')
        ])

        # Convert to list of dictionaries
        return result.to_dicts()

    def _get_monthly_trends(self, start_date, end_date):
        """Get monthly trends for assets, transfers, and maintenance"""
        # Asset acquisitions by month
        monthly_assets = Asset.objects.filter(
            is_active=True,
            purchase_date__gte=start_date,
            purchase_date__lte=end_date
        ).annotate(
            month=TruncMonth('purchase_date')
        ).values('month').annotate(count=Count('id')).order_by('month')

        # Transfers by month
        monthly_transfers = AssetTransfer.objects.filter(
            transfer_date__gte=start_date,
            transfer_date__lte=end_date
        ).annotate(
            month=TruncMonth('transfer_date')
        ).values('month').annotate(count=Count('id')).order_by('month')

        # Maintenance completed by month
        monthly_maintenance = AssetMaintenance.objects.filter(
            status='completed',
            completed_date__gte=start_date,
            completed_date__lte=end_date
        ).annotate(
            month=TruncMonth('completed_date')
        ).values('month').annotate(count=Count('id')).order_by('month')

        # Create a complete 12-month range
        months = []
        current = start_date.replace(day=1)
        while current <= end_date:
            month_str = current.strftime('%Y-%m')
            months.append(month_str)
            current = (current + timedelta(days=32)).replace(day=1)

        # Build trend data
        trends = []
        for month in months:
            trends.append({
                'month': month,
                'assets_acquired': next(
                    (item['count'] for item in monthly_assets if item['month'].strftime('%Y-%m') == month),
                    0
                ),
                'transfers': next(
                    (item['count'] for item in monthly_transfers if item['month'].strftime('%Y-%m') == month),
                    0
                ),
                'maintenance_completed': next(
                    (item['count'] for item in monthly_maintenance if item['month'].strftime('%Y-%m') == month),
                    0
                ),
            })

        return trends
