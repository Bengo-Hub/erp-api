from rest_framework import serializers
from .models import CustomerAnalytics, SalesForecast, CustomerSegment, AnalyticsSnapshot
from crm.contacts.serializers import ContactSerializer
from ecommerce.product.serializers import ProductsSerializer
from business.serializers import BranchSerializer

class CustomerAnalyticsSerializer(serializers.ModelSerializer):
    """Serializer for CustomerAnalytics model"""
    
    customer = ContactSerializer(read_only=True)
    customer_id = serializers.IntegerField(write_only=True)
    branch = BranchSerializer(read_only=True)
    branch_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = CustomerAnalytics
        fields = [
            'id', 'customer', 'customer_id', 'branch', 'branch_id',
            'total_orders', 'total_spent', 'average_order_value', 'customer_lifetime_value',
            'retention_rate', 'first_order_date', 'last_order_date', 'days_since_last_order',
            'order_frequency', 'customer_segment', 'created_at', 'updated_at'
        ]
        read_only_fields = [
            'total_orders', 'total_spent', 'average_order_value', 'customer_lifetime_value',
            'retention_rate', 'first_order_date', 'last_order_date', 'days_since_last_order',
            'order_frequency', 'customer_segment', 'created_at', 'updated_at'
        ]

class SalesForecastSerializer(serializers.ModelSerializer):
    """Serializer for SalesForecast model"""
    
    product = ProductsSerializer(read_only=True)
    product_id = serializers.IntegerField(write_only=True, required=False, allow_null=True)
    branch = BranchSerializer(read_only=True)
    branch_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = SalesForecast
        fields = [
            'id', 'branch', 'branch_id', 'product', 'product_id',
            'forecast_date', 'forecast_period', 'predicted_quantity', 'predicted_revenue',
            'confidence_level', 'growth_rate', 'historical_quantity', 'historical_revenue',
            'seasonal_factor', 'created_at', 'updated_at'
        ]

class CustomerSegmentSerializer(serializers.ModelSerializer):
    """Serializer for CustomerSegment model"""
    
    branch = BranchSerializer(read_only=True)
    branch_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = CustomerSegment
        fields = [
            'id', 'branch', 'branch_id', 'segment_name',
            'segment_description', 'min_orders', 'max_orders', 'min_total_spent',
            'max_total_spent', 'min_days_since_last_order', 'max_days_since_last_order',
            'customer_count', 'average_order_value', 'total_revenue', 'created_at', 'updated_at'
        ]
        read_only_fields = ['customer_count', 'average_order_value', 'total_revenue', 'created_at', 'updated_at']

class AnalyticsSnapshotSerializer(serializers.ModelSerializer):
    """Serializer for AnalyticsSnapshot model"""
    
    branch = BranchSerializer(read_only=True)
    branch_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = AnalyticsSnapshot
        fields = [
            'id', 'branch', 'snapshot_date',
            'snapshot_type', 'total_customers', 'new_customers', 'active_customers',
            'churned_customers', 'total_orders', 'total_revenue', 'average_order_value',
            'conversion_rate', 'retention_rate', 'created_at'
        ]
        read_only_fields = [
            'total_customers', 'new_customers', 'active_customers', 'churned_customers',
            'total_orders', 'total_revenue', 'average_order_value', 'conversion_rate',
            'retention_rate', 'created_at'
        ]

class CustomerAnalyticsSummarySerializer(serializers.Serializer):
    """Serializer for customer analytics summary data"""
    
    total_customers = serializers.IntegerField()
    new_customers = serializers.IntegerField()
    active_customers = serializers.IntegerField()
    loyal_customers = serializers.IntegerField()
    at_risk_customers = serializers.IntegerField()
    churned_customers = serializers.IntegerField()
    average_customer_lifetime_value = serializers.DecimalField(max_digits=15, decimal_places=2)
    average_order_value = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_revenue = serializers.DecimalField(max_digits=15, decimal_places=2)

class SalesForecastSummarySerializer(serializers.Serializer):
    """Serializer for sales forecast summary data"""
    
    total_predicted_revenue = serializers.DecimalField(max_digits=15, decimal_places=2)
    total_predicted_quantity = serializers.IntegerField()
    average_confidence_level = serializers.DecimalField(max_digits=5, decimal_places=2)
    average_growth_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
    forecast_periods = serializers.ListField(child=serializers.CharField())
    top_products = serializers.ListField(child=serializers.DictField())

class CustomerBehaviorSerializer(serializers.Serializer):
    """Serializer for customer behavior analysis"""
    
    customer_id = serializers.IntegerField()
    customer_name = serializers.CharField()
    total_orders = serializers.IntegerField()
    total_spent = serializers.DecimalField(max_digits=15, decimal_places=2)
    average_order_value = serializers.DecimalField(max_digits=15, decimal_places=2)
    days_since_last_order = serializers.IntegerField()
    customer_segment = serializers.CharField()
    order_frequency = serializers.DecimalField(max_digits=5, decimal_places=2)
    retention_score = serializers.DecimalField(max_digits=5, decimal_places=2)

class SeasonalTrendSerializer(serializers.Serializer):
    """Serializer for seasonal trend analysis"""
    
    period = serializers.CharField()
    revenue = serializers.DecimalField(max_digits=15, decimal_places=2)
    quantity = serializers.IntegerField()
    seasonal_factor = serializers.DecimalField(max_digits=5, decimal_places=2)
    growth_rate = serializers.DecimalField(max_digits=5, decimal_places=2)
