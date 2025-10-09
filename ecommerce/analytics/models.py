from django.db import models
from django.contrib.auth import get_user_model
from django.utils import timezone
from datetime import datetime, timedelta
from decimal import Decimal
from django.db.models import Q
from core.models import BaseModel
from core_orders.models import BaseOrder

User = get_user_model()

class CustomerAnalytics(models.Model):
    """Model to store customer analytics data"""
    
    # Basic customer info
    customer = models.ForeignKey('contacts.Contact', on_delete=models.CASCADE, related_name='analytics')
    branch = models.ForeignKey('business.Branch', on_delete=models.CASCADE, related_name='customer_analytics')
    
    # Analytics metrics
    total_orders = models.IntegerField(default=0)
    total_spent = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    average_order_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    customer_lifetime_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    retention_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Behavioral metrics
    first_order_date = models.DateTimeField(null=True, blank=True)
    last_order_date = models.DateTimeField(null=True, blank=True)
    days_since_last_order = models.IntegerField(default=0)
    order_frequency = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Segmentation
    customer_segment = models.CharField(max_length=50, choices=[
        ('new', 'New Customer'),
        ('active', 'Active Customer'),
        ('loyal', 'Loyal Customer'),
        ('at_risk', 'At Risk Customer'),
        ('churned', 'Churned Customer'),
    ], default='new')
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Customer Analytics"
        verbose_name_plural = "Customer Analytics"
        unique_together = ['customer', 'branch']
        indexes = [
            models.Index(fields=['customer_segment'], name='idx_customer_analytics_segment'),
            models.Index(fields=['total_spent'], name='idx_cust_analytics_spent'),
            models.Index(fields=['last_order_date'], name='idx_cust_analytics_last_order'),
            models.Index(fields=['customer'], name='idx_cust_analytics_customer'),
            models.Index(fields=['branch'], name='idx_cust_analytics_branch'),
            models.Index(fields=['created_at'], name='idx_cust_analytics_created'),
        ]
    
    def __str__(self):
        return f"{self.customer} - {self.customer_segment}"
    
    def update_analytics(self):
        """Update analytics based on recent orders"""
        
        # Get customer orders
        orders = BaseOrder.objects.filter(
            customer=self.customer,
            branch=self.branch,
            status__in=['completed', 'delivered']
        ).order_by('created_at')
        
        if orders.exists():
            self.total_orders = orders.count()
            self.total_spent = orders.aggregate(total=models.Sum('total_amount'))['total'] or Decimal('0.00')
            self.average_order_value = self.total_spent / self.total_orders
            
            # First and last order dates
            first_order = orders.first()
            last_order = orders.last()
            if first_order:
                self.first_order_date = first_order.created_at
            if last_order:
                self.last_order_date = last_order.created_at
            
            # Days since last order
            if self.last_order_date:
                self.days_since_last_order = (timezone.now() - self.last_order_date).days
            
            # Order frequency (orders per month)
            if self.first_order_date and self.last_order_date:
                months_diff = (self.last_order_date.year - self.first_order_date.year) * 12 + \
                             (self.last_order_date.month - self.first_order_date.month)
                if months_diff > 0:
                    self.order_frequency = self.total_orders / months_diff
                else:
                    self.order_frequency = self.total_orders
            
            # Customer lifetime value (total spent)
            self.customer_lifetime_value = self.total_spent
            
            # Update customer segment
            self._update_customer_segment()
            
            self.save()
    
    def _update_customer_segment(self):
        """Update customer segment based on behavior"""
        if self.total_orders == 0:
            self.customer_segment = 'new'
        elif self.days_since_last_order <= 30:
            if self.total_orders >= 5:
                self.customer_segment = 'loyal'
            else:
                self.customer_segment = 'active'
        elif self.days_since_last_order <= 90:
            self.customer_segment = 'at_risk'
        else:
            self.customer_segment = 'churned'

class SalesForecast(models.Model):
    """Model to store sales forecasting data"""
    
    branch = models.ForeignKey('business.Branch', on_delete=models.CASCADE, related_name='sales_forecasts')
    product = models.ForeignKey('product.Products', on_delete=models.CASCADE, null=True, blank=True)
    
    # Forecast period
    forecast_date = models.DateField()
    forecast_period = models.CharField(max_length=20, choices=[
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly'),
    ])
    
    # Forecast metrics
    predicted_quantity = models.IntegerField(default=0)
    predicted_revenue = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    confidence_level = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    growth_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Historical data for comparison
    historical_quantity = models.IntegerField(default=0)
    historical_revenue = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Seasonal factors
    seasonal_factor = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('1.00'))
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Sales Forecast"
        verbose_name_plural = "Sales Forecasts"
        unique_together = ['branch', 'product', 'forecast_date', 'forecast_period']
        indexes = [
            models.Index(fields=['forecast_date'], name='idx_sales_forecast_date'),
            models.Index(fields=['forecast_period'], name='idx_sales_forecast_period'),
            models.Index(fields=['product'], name='idx_sales_forecast_product'),
            models.Index(fields=['branch'], name='idx_sales_forecast_branch'),
            models.Index(fields=['created_at'], name='idx_sales_forecast_created_at'),
        ]
    
    def __str__(self):
        product_name = self.product.title if self.product else "All Products"
        return f"{product_name} - {self.forecast_date} ({self.forecast_period})"

class CustomerSegment(models.Model):
    """Model to store customer segmentation data"""
    
    branch = models.ForeignKey('business.Branch', on_delete=models.CASCADE, related_name='customer_segments')
    segment_name = models.CharField(max_length=100)
    segment_description = models.TextField(blank=True)
    
    # Segment criteria
    min_orders = models.IntegerField(default=0)
    max_orders = models.IntegerField(null=True, blank=True)
    min_total_spent = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    max_total_spent = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    min_days_since_last_order = models.IntegerField(default=0)
    max_days_since_last_order = models.IntegerField(null=True, blank=True)
    
    # Segment metrics
    customer_count = models.IntegerField(default=0)
    average_order_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_revenue = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = "Customer Segment"
        verbose_name_plural = "Customer Segments"
        unique_together = ['branch', 'segment_name']
        indexes = [
            models.Index(fields=['branch'], name='idx_customer_segment_branch'),
            models.Index(fields=['segment_name'], name='idx_customer_segment_name'),
            models.Index(fields=['created_at'], name='idx_cust_segment_created'),
        ]
    
    def __str__(self):
        return f"{self.segment_name} - {self.branch}"
    
    def update_segment_metrics(self):
        """Update segment metrics based on current customers"""
        
        # Build query based on segment criteria
        query = Q(branch=self.branch)
        
        if self.min_orders > 0:
            query &= Q(analytics__total_orders__gte=self.min_orders)
        if self.max_orders:
            query &= Q(analytics__total_orders__lte=self.max_orders)
        
        if self.min_total_spent > 0:
            query &= Q(analytics__total_spent__gte=self.min_total_spent)
        if self.max_total_spent:
            query &= Q(analytics__total_spent__lte=self.max_total_spent)
        
        if self.min_days_since_last_order > 0:
            query &= Q(analytics__days_since_last_order__gte=self.min_days_since_last_order)
        if self.max_days_since_last_order:
            query &= Q(analytics__days_since_last_order__lte=self.max_days_since_last_order)
        
        # Get customers in this segment
        customers = CustomerAnalytics.objects.filter(query)
        
        self.customer_count = customers.count()
        
        if self.customer_count > 0:
            self.average_order_value = customers.aggregate(
                avg=models.Avg('average_order_value')
            )['avg'] or Decimal('0.00')
            self.total_revenue = customers.aggregate(
                total=models.Sum('total_spent')
            )['total'] or Decimal('0.00')
        
        self.save()

class AnalyticsSnapshot(models.Model):
    """Model to store periodic analytics snapshots for trend analysis"""
    
    branch = models.ForeignKey('business.Branch', on_delete=models.CASCADE, related_name='analytics_snapshots')
    snapshot_date = models.DateField()
    snapshot_type = models.CharField(max_length=20, choices=[
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
    ])
    
    # Customer metrics
    total_customers = models.IntegerField(default=0)
    new_customers = models.IntegerField(default=0)
    active_customers = models.IntegerField(default=0)
    churned_customers = models.IntegerField(default=0)
    
    # Sales metrics
    total_orders = models.IntegerField(default=0)
    total_revenue = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    average_order_value = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Conversion metrics
    conversion_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    retention_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'))
    
    # Timestamps
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = "Analytics Snapshot"
        verbose_name_plural = "Analytics Snapshots"
        unique_together = ['branch', 'snapshot_date', 'snapshot_type']
        indexes = [
            models.Index(fields=['snapshot_date'], name='idx_analytics_snapshot_date'),
            models.Index(fields=['snapshot_type'], name='idx_analytics_snapshot_type'),
            models.Index(fields=['branch'], name='idx_analytics_snapshot_branch'),
            models.Index(fields=['created_at'], name='idx_analytics_snapshot_created'),
        ]
    
    def __str__(self):
        return f"{self.branch} - {self.snapshot_date} ({self.snapshot_type})"
