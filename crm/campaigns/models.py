from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from crm.contacts.models import Contact
from business.models import Branch
from ecommerce.stockinventory.models import StockInventory
from decimal import Decimal

User = get_user_model()

class Campaign(models.Model):
    """Marketing campaign model for CRM"""
    
    CAMPAIGN_TYPES = [
        ('banner', 'Banner'),
        ('email', 'Email'),
        ('social', 'Social Media'),
        ('sms', 'SMS'),
        ('promotional', 'Promotional'),
        ('seasonal', 'Seasonal'),
        ('product_launch', 'Product Launch'),
        ('loyalty', 'Loyalty Program'),
    ]
    
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('paused', 'Paused'),
        ('completed', 'Completed'),
        ('cancelled', 'Cancelled'),
    ]
    
    PRIORITY_CHOICES = [
        (1, 'Highest'),
        (2, 'High'),
        (3, 'Medium'),
        (4, 'Low'),
        (5, 'Lowest'),
    ]
    
    name = models.CharField(max_length=255)
    campaign_type = models.CharField(max_length=50, choices=CAMPAIGN_TYPES, default='banner')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    priority = models.IntegerField(choices=PRIORITY_CHOICES, default=3)
    
    # Campaign content
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to='campaigns/', null=True, blank=True)
    badge = models.CharField(max_length=200, blank=True, null=True, default="New")
    
    # Campaign targeting
    target_audience = models.ManyToManyField(Contact, blank=True, related_name='targeted_campaigns')
    target_branches = models.ManyToManyField(Branch, blank=True, related_name='targeted_campaigns')
    featured_products = models.ManyToManyField(StockInventory, blank=True, related_name='product_campaigns')
    
    # Banner-specific fields (for backward compatibility)
    seller = models.ForeignKey(
        Contact, 
        on_delete=models.CASCADE,
        related_name='seller_campaigns',
        null=True,
        blank=True,
        limit_choices_to={'contact_type': 'Suppliers'}
    )
    stock_items = models.ManyToManyField(StockInventory, blank=True, related_name='stock_campaigns')
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='campaigns', null=True, blank=True)
    
    # Campaign timing
    start_date = models.DateTimeField()
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    is_default = models.BooleanField(default=False)
    
    # Campaign metrics
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    revenue_generated = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    # Campaign settings
    budget = models.DecimalField(max_digits=15, decimal_places=2, null=True, blank=True)
    max_impressions = models.PositiveIntegerField(null=True, blank=True)
    max_clicks = models.PositiveIntegerField(null=True, blank=True)
    
    # Campaign links
    landing_page_url = models.URLField(blank=True, null=True)
    cta_text = models.CharField(max_length=100, blank=True, default="Learn More")
    
    # Metadata
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='created_campaigns', null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'crm_campaigns'
        ordering = ['priority', '-start_date']
        indexes = [
            models.Index(fields=['campaign_type'], name='idx_campaign_type'),
            models.Index(fields=['status'], name='idx_campaign_status'),
            models.Index(fields=['priority'], name='idx_campaign_priority'),
            models.Index(fields=['is_active'], name='idx_campaign_active'),
            models.Index(fields=['start_date'], name='idx_campaign_start_date'),
            models.Index(fields=['end_date'], name='idx_campaign_end_date'),
            models.Index(fields=['created_at'], name='idx_campaign_created_at'),
            models.Index(fields=['seller'], name='idx_campaign_seller'),
            models.Index(fields=['branch'], name='idx_campaign_branch'),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.get_campaign_type_display()})"
    
    @property
    def is_running(self):
        """Check if campaign is currently running"""
        now = timezone.now()
        return (
            self.is_active and 
            self.status == 'active' and
            self.start_date <= now <= self.end_date
        )
    
    @property
    def ctr(self):
        """Calculate click-through rate"""
        if self.impressions == 0:
            return 0.0
        return (self.clicks / self.impressions) * 100
    
    @property
    def conversion_rate(self):
        """Calculate conversion rate"""
        if self.clicks == 0:
            return 0.0
        return (self.conversions / self.clicks) * 100
    
    def increment_impression(self):
        """Increment impression count"""
        self.impressions += 1
        self.save(update_fields=['impressions'])
    
    def increment_click(self):
        """Increment click count"""
        self.clicks += 1
        self.save(update_fields=['clicks'])
    
    def increment_conversion(self, revenue=0):
        """Increment conversion count and revenue"""
        self.conversions += 1
        self.revenue_generated += revenue
        self.save(update_fields=['conversions', 'revenue_generated'])
    
    def get_roi(self):
        """Calculate return on investment"""
        if not self.budget or self.budget == 0:
            return 0.0
        return ((self.revenue_generated - self.budget) / self.budget) * 100


class CampaignPerformance(models.Model):
    """Track daily campaign performance metrics"""
    
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name='daily_performance')
    date = models.DateField()
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)
    conversions = models.PositiveIntegerField(default=0)
    revenue = models.DecimalField(max_digits=15, decimal_places=2, default=Decimal('0.00'))
    
    class Meta:
        db_table = 'crm_campaign_performance'
        unique_together = ['campaign', 'date']
        ordering = ['-date']
        indexes = [
            models.Index(fields=['campaign', 'date'], name='idx_campaign_performance_date'),
        ]
    
    def __str__(self):
        return f"{self.campaign.name} - {self.date}"
