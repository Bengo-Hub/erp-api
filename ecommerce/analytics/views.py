from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q, Sum, Avg, Count, F
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal

from .models import CustomerAnalytics, SalesForecast, CustomerSegment, AnalyticsSnapshot
from .serializers import (
    CustomerAnalyticsSerializer, SalesForecastSerializer, CustomerSegmentSerializer,
    AnalyticsSnapshotSerializer, CustomerAnalyticsSummarySerializer, SalesForecastSummarySerializer,
    CustomerBehaviorSerializer, SeasonalTrendSerializer
)

class CustomerAnalyticsViewSet(viewsets.ModelViewSet):
    """ViewSet for CustomerAnalytics model"""
    
    queryset = CustomerAnalytics.objects.all()
    serializer_class = CustomerAnalyticsSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter queryset based on business location"""
        queryset = super().get_queryset()
        branch_id = self.request.query_params.get('branch_id')
        if branch_id:
            queryset = queryset.filter(branch_id=branch_id)
        return queryset
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get customer analytics summary"""
        business_location_id = request.query_params.get('business_location_id')
        queryset = self.get_queryset()
        
        if business_location_id:
            queryset = queryset.filter(business_location_id=business_location_id)
        
        # Calculate summary metrics
        summary_data = {
            'total_customers': queryset.count(),
            'new_customers': queryset.filter(customer_segment='new').count(),
            'active_customers': queryset.filter(customer_segment='active').count(),
            'loyal_customers': queryset.filter(customer_segment='loyal').count(),
            'at_risk_customers': queryset.filter(customer_segment='at_risk').count(),
            'churned_customers': queryset.filter(customer_segment='churned').count(),
            'average_customer_lifetime_value': queryset.aggregate(
                avg=Avg('customer_lifetime_value')
            )['avg'] or Decimal('0.00'),
            'average_order_value': queryset.aggregate(
                avg=Avg('average_order_value')
            )['avg'] or Decimal('0.00'),
            'total_revenue': queryset.aggregate(
                total=Sum('total_spent')
            )['total'] or Decimal('0.00'),
        }
        
        serializer = CustomerAnalyticsSummarySerializer(summary_data)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def top_customers(self, request):
        """Get top customers by revenue"""
        business_location_id = request.query_params.get('business_location_id')
        limit = int(request.query_params.get('limit', 10))
        
        queryset = self.get_queryset()
        if business_location_id:
            queryset = queryset.filter(business_location_id=business_location_id)
        
        top_customers = queryset.order_by('-total_spent')[:limit]
        serializer = self.get_serializer(top_customers, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def customer_behavior(self, request):
        """Get customer behavior analysis"""
        business_location_id = request.query_params.get('business_location_id')
        segment = request.query_params.get('segment')
        
        queryset = self.get_queryset()
        if business_location_id:
            queryset = queryset.filter(business_location_id=business_location_id)
        if segment:
            queryset = queryset.filter(customer_segment=segment)
        
        behavior_data = []
        for analytics in queryset:
            behavior_data.append({
                'customer_id': analytics.customer.id,
                'customer_name': f"{analytics.customer.first_name} {analytics.customer.last_name}",
                'total_orders': analytics.total_orders,
                'total_spent': analytics.total_spent,
                'average_order_value': analytics.average_order_value,
                'days_since_last_order': analytics.days_since_last_order,
                'customer_segment': analytics.customer_segment,
                'order_frequency': analytics.order_frequency,
                'retention_score': analytics.retention_rate,
            })
        
        serializer = CustomerBehaviorSerializer(behavior_data, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def update_analytics(self, request):
        """Update analytics for all customers"""
        business_location_id = request.data.get('business_location_id')
        
        queryset = self.get_queryset()
        if business_location_id:
            queryset = queryset.filter(business_location_id=business_location_id)
        
        updated_count = 0
        for analytics in queryset:
            analytics.update_analytics()
            updated_count += 1
        
        return Response({
            'message': f'Updated analytics for {updated_count} customers',
            'updated_count': updated_count
        })

class SalesForecastViewSet(viewsets.ModelViewSet):
    """ViewSet for SalesForecast model"""
    
    queryset = SalesForecast.objects.all()
    serializer_class = SalesForecastSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter queryset based on business location and date range"""
        queryset = super().get_queryset()
        business_location_id = self.request.query_params.get('business_location_id')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        forecast_period = self.request.query_params.get('forecast_period')
        
        if business_location_id:
            queryset = queryset.filter(business_location_id=business_location_id)
        if start_date:
            queryset = queryset.filter(forecast_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(forecast_date__lte=end_date)
        if forecast_period:
            queryset = queryset.filter(forecast_period=forecast_period)
        
        return queryset
    
    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Get sales forecast summary"""
        business_location_id = request.query_params.get('business_location_id')
        queryset = self.get_queryset()
        
        if business_location_id:
            queryset = queryset.filter(business_location_id=business_location_id)
        
        # Calculate summary metrics
        summary_data = {
            'total_predicted_revenue': queryset.aggregate(
                total=Sum('predicted_revenue')
            )['total'] or Decimal('0.00'),
            'total_predicted_quantity': queryset.aggregate(
                total=Sum('predicted_quantity')
            )['total'] or 0,
            'average_confidence_level': queryset.aggregate(
                avg=Avg('confidence_level')
            )['avg'] or Decimal('0.00'),
            'average_growth_rate': queryset.aggregate(
                avg=Avg('growth_rate')
            )['avg'] or Decimal('0.00'),
            'forecast_periods': list(queryset.values_list('forecast_period', flat=True).distinct()),
            'top_products': list(queryset.values('product__title', 'predicted_revenue').order_by('-predicted_revenue')[:5])
        }
        
        serializer = SalesForecastSummarySerializer(summary_data)
        return Response(serializer.data)
    
    @action(detail=False, methods=['get'])
    def seasonal_trends(self, request):
        """Get seasonal trend analysis"""
        business_location_id = request.query_params.get('business_location_id')
        queryset = self.get_queryset()
        
        if business_location_id:
            queryset = queryset.filter(business_location_id=business_location_id)
        
        # Group by period and calculate trends
        trends_data = []
        for forecast in queryset.order_by('forecast_date'):
            trends_data.append({
                'period': forecast.forecast_date.strftime('%Y-%m-%d'),
                'revenue': forecast.predicted_revenue,
                'quantity': forecast.predicted_quantity,
                'seasonal_factor': forecast.seasonal_factor,
                'growth_rate': forecast.growth_rate,
            })
        
        serializer = SeasonalTrendSerializer(trends_data, many=True)
        return Response(serializer.data)
    
    @action(detail=False, methods=['post'])
    def generate_forecast(self, request):
        """Generate sales forecast for a specific period"""
        business_location_id = request.data.get('business_location_id')
        product_id = request.data.get('product_id')
        forecast_period = request.data.get('forecast_period', 'monthly')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        
        if not all([business_location_id, start_date, end_date]):
            return Response({
                'error': 'business_location_id, start_date, and end_date are required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Simple forecasting logic (in a real implementation, this would use ML models)
        from ecommerce.order.models import Order
        
        # Get historical data
        historical_orders = Order.objects.filter(
            business_location_id=business_location_id,
            status__in=['completed', 'delivered'],
            created_at__date__range=[start_date, end_date]
        )
        
        if product_id:
            historical_orders = historical_orders.filter(items__product_id=product_id)
        
        # Calculate historical metrics
        historical_revenue = historical_orders.aggregate(
            total=Sum('total_amount')
        )['total'] or Decimal('0.00')
        
        historical_quantity = historical_orders.count()
        
        # Simple growth prediction (10% growth)
        predicted_revenue = historical_revenue * Decimal('1.10')
        predicted_quantity = int(historical_quantity * 1.10)
        
        # Create forecast records
        created_forecasts = []
        current_date = datetime.strptime(start_date, '%Y-%m-%d').date()
        end_date_obj = datetime.strptime(end_date, '%Y-%m-%d').date()
        
        while current_date <= end_date_obj:
            forecast, created = SalesForecast.objects.get_or_create(
                business_location_id=business_location_id,
                product_id=product_id,
                forecast_date=current_date,
                forecast_period=forecast_period,
                defaults={
                    'predicted_quantity': predicted_quantity,
                    'predicted_revenue': predicted_revenue,
                    'confidence_level': Decimal('0.85'),
                    'growth_rate': Decimal('0.10'),
                    'historical_quantity': historical_quantity,
                    'historical_revenue': historical_revenue,
                    'seasonal_factor': Decimal('1.00'),
                }
            )
            
            if created:
                created_forecasts.append(forecast)
            
            # Move to next period
            if forecast_period == 'daily':
                current_date += timedelta(days=1)
            elif forecast_period == 'weekly':
                current_date += timedelta(weeks=1)
            elif forecast_period == 'monthly':
                # Simple month increment
                if current_date.month == 12:
                    current_date = current_date.replace(year=current_date.year + 1, month=1)
                else:
                    current_date = current_date.replace(month=current_date.month + 1)
        
        serializer = self.get_serializer(created_forecasts, many=True)
        return Response({
            'message': f'Generated {len(created_forecasts)} forecast records',
            'forecasts': serializer.data
        })

class CustomerSegmentViewSet(viewsets.ModelViewSet):
    """ViewSet for CustomerSegment model"""
    
    queryset = CustomerSegment.objects.all()
    serializer_class = CustomerSegmentSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter queryset based on business location"""
        queryset = super().get_queryset()
        business_location_id = self.request.query_params.get('business_location_id')
        if business_location_id:
            queryset = queryset.filter(business_location_id=business_location_id)
        return queryset
    
    @action(detail=True, methods=['post'])
    def update_metrics(self, request, pk=None):
        """Update segment metrics"""
        segment = self.get_object()
        segment.update_segment_metrics()
        serializer = self.get_serializer(segment)
        return Response(serializer.data)

class AnalyticsSnapshotViewSet(viewsets.ModelViewSet):
    """ViewSet for AnalyticsSnapshot model"""
    
    queryset = AnalyticsSnapshot.objects.all()
    serializer_class = AnalyticsSnapshotSerializer
    permission_classes = [IsAuthenticated]
    
    def get_queryset(self):
        """Filter queryset based on business location and date range"""
        queryset = super().get_queryset()
        business_location_id = self.request.query_params.get('business_location_id')
        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        snapshot_type = self.request.query_params.get('snapshot_type')
        
        if business_location_id:
            queryset = queryset.filter(business_location_id=business_location_id)
        if start_date:
            queryset = queryset.filter(snapshot_date__gte=start_date)
        if end_date:
            queryset = queryset.filter(snapshot_date__lte=end_date)
        if snapshot_type:
            queryset = queryset.filter(snapshot_type=snapshot_type)
        
        return queryset
    
    @action(detail=False, methods=['post'])
    def create_snapshot(self, request):
        """Create a new analytics snapshot"""
        business_location_id = request.data.get('business_location_id')
        snapshot_type = request.data.get('snapshot_type', 'daily')
        snapshot_date = request.data.get('snapshot_date', timezone.now().date())
        
        if not business_location_id:
            return Response({
                'error': 'business_location_id is required'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Calculate snapshot metrics
        from core_orders.models import BaseOrder
        from crm.contacts.models import Contact
        
        # Customer metrics
        total_customers = Contact.objects.filter(business_location_id=business_location_id).count()
        
        # Get customer analytics for the business location
        customer_analytics = CustomerAnalytics.objects.filter(business_location_id=business_location_id)
        
        new_customers = customer_analytics.filter(customer_segment='new').count()
        active_customers = customer_analytics.filter(customer_segment='active').count()
        churned_customers = customer_analytics.filter(customer_segment='churned').count()
        
        # Sales metrics for the snapshot date
        orders = BaseOrder.objects.filter(
            business_location_id=business_location_id,
            created_at__date=snapshot_date,
            status__in=['completed', 'delivered']
        )
        
        total_orders = orders.count()
        total_revenue = orders.aggregate(total=Sum('total_amount'))['total'] or Decimal('0.00')
        average_order_value = total_revenue / total_orders if total_orders > 0 else Decimal('0.00')
        
        # Create snapshot
        snapshot, created = AnalyticsSnapshot.objects.get_or_create(
            business_location_id=business_location_id,
            snapshot_date=snapshot_date,
            snapshot_type=snapshot_type,
            defaults={
                'total_customers': total_customers,
                'new_customers': new_customers,
                'active_customers': active_customers,
                'churned_customers': churned_customers,
                'total_orders': total_orders,
                'total_revenue': total_revenue,
                'average_order_value': average_order_value,
                'conversion_rate': Decimal('0.00'),  # Would need more complex calculation
                'retention_rate': Decimal('0.00'),   # Would need more complex calculation
            }
        )
        
        serializer = self.get_serializer(snapshot)
        return Response(serializer.data)
