from django.contrib import admin
from .models import CustomerAnalytics, SalesForecast, CustomerSegment, AnalyticsSnapshot

@admin.register(CustomerAnalytics)
class CustomerAnalyticsAdmin(admin.ModelAdmin):
    list_display = [
        'customer', 'branch', 'customer_segment', 'total_orders',
        'total_spent', 'average_order_value', 'days_since_last_order'
    ]
    list_filter = ['customer_segment', 'branch', 'created_at']
    search_fields = ['customer__first_name', 'customer__last_name', 'customer__email']
    readonly_fields = [
        'total_orders', 'total_spent', 'average_order_value', 'customer_lifetime_value',
        'retention_rate', 'first_order_date', 'last_order_date', 'days_since_last_order',
        'order_frequency', 'customer_segment', 'created_at', 'updated_at'
    ]
    
    actions = ['update_analytics']
    
    def update_analytics(self, request, queryset):
        """Update analytics for selected customers"""
        updated_count = 0
        for analytics in queryset:
            analytics.update_analytics()
            updated_count += 1
        
        self.message_user(request, f'Updated analytics for {updated_count} customers')
    update_analytics.short_description = "Update analytics for selected customers"

@admin.register(SalesForecast)
class SalesForecastAdmin(admin.ModelAdmin):
    list_display = [
        'branch', 'product', 'forecast_date', 'forecast_period',
        'predicted_quantity', 'predicted_revenue', 'confidence_level'
    ]
    list_filter = ['forecast_period', 'branch', 'forecast_date']
    search_fields = ['product__title', 'branch__name']
    readonly_fields = ['created_at', 'updated_at']

@admin.register(CustomerSegment)
class CustomerSegmentAdmin(admin.ModelAdmin):
    list_display = [
        'segment_name', 'branch', 'customer_count',
        'average_order_value', 'total_revenue'
    ]
    list_filter = ['branch', 'created_at']
    search_fields = ['segment_name', 'segment_description']
    readonly_fields = ['customer_count', 'average_order_value', 'total_revenue', 'created_at', 'updated_at']
    
    actions = ['update_segment_metrics']
    
    def update_segment_metrics(self, request, queryset):
        """Update metrics for selected segments"""
        updated_count = 0
        for segment in queryset:
            segment.update_segment_metrics()
            updated_count += 1
        
        self.message_user(request, f'Updated metrics for {updated_count} segments')
    update_segment_metrics.short_description = "Update metrics for selected segments"

@admin.register(AnalyticsSnapshot)
class AnalyticsSnapshotAdmin(admin.ModelAdmin):
    list_display = [
        'branch', 'snapshot_date', 'snapshot_type',
        'total_customers', 'total_orders', 'total_revenue'
    ]
    list_filter = ['snapshot_type', 'branch', 'snapshot_date']
    search_fields = ['branch__name']
    readonly_fields = [
        'total_customers', 'new_customers', 'active_customers', 'churned_customers',
        'total_orders', 'total_revenue', 'average_order_value', 'conversion_rate',
        'retention_rate', 'created_at'
    ]
