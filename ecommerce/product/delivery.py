from django.db import models
from business.models import Bussiness
from addresses.models import DeliveryRegion
from ecommerce.product.models import Products
from django.utils.translation import gettext_lazy as _

class DeliveryPolicy(models.Model):
    """Defines delivery policies for products or product categories"""
    DELIVERY_SPEED_CHOICES = [
        ('express', _('Express (Same Day)')),
        ('next_day', _('Next Day')),
        ('standard', _('Standard (2-4 days)')),
        ('economy', _('Economy (5-7 days)')),
        ('international', _('International (7-14 days)')),
    ]

    business = models.ForeignKey(Bussiness, on_delete=models.CASCADE, related_name="delivery_policies")
    name = models.CharField(max_length=100, help_text=_("Name of the delivery policy"))
    description = models.TextField(blank=True, null=True, help_text=_("Detailed description of the delivery policy"))
    
    # Time estimates
    min_days = models.PositiveSmallIntegerField(default=1, help_text=_("Minimum number of days for delivery"))
    max_days = models.PositiveSmallIntegerField(default=3, help_text=_("Maximum number of days for delivery"))
    delivery_speed = models.CharField(max_length=20, choices=DELIVERY_SPEED_CHOICES, default='standard')
    
    # Applicability
    is_default = models.BooleanField(default=False, help_text=_("Set as the default policy"))
    is_active = models.BooleanField(default=True)
    
    # Pricing
    base_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, 
                                    help_text=_("Base delivery fee"))
    
    # Special conditions
    free_delivery_threshold = models.DecimalField(max_digits=10, decimal_places=2, default=0.00,
                                               help_text=_("Order amount above which delivery is free (0 means no free delivery)"))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'delivery_policies'
        verbose_name = _('Delivery Policy')
        verbose_name_plural = _('Delivery Policies')
        
    def __str__(self):
        return self.name


class RegionalDeliveryPolicy(models.Model):
    """Region-specific delivery policies"""
    policy = models.ForeignKey(DeliveryPolicy, on_delete=models.CASCADE, related_name="regional_policies")
    region = models.ForeignKey(DeliveryRegion, on_delete=models.CASCADE, related_name="delivery_policies")
    
    # Region-specific time estimates
    min_days = models.PositiveSmallIntegerField(null=True, blank=True, 
                                          help_text=_("Region-specific min days (overrides policy default)"))
    max_days = models.PositiveSmallIntegerField(null=True, blank=True,
                                          help_text=_("Region-specific max days (overrides policy default)"))
    
    # Region-specific fees
    delivery_fee = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True,
                                    help_text=_("Region-specific delivery fee (overrides policy default)"))
    
    class Meta:
        db_table = 'regional_delivery_policies'
        verbose_name = _('Regional Delivery Policy')
        verbose_name_plural = _('Regional Delivery Policies')
        unique_together = ('policy', 'region')
        
    def __str__(self):
        return f"{self.policy.name} - {self.region.region}"


class ProductDeliveryInfo(models.Model):
    """Product-specific delivery information"""
    product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name="delivery_info")
    policy = models.ForeignKey(DeliveryPolicy, on_delete=models.CASCADE, related_name="product_policies")
    
    # Special product-specific overrides
    special_handling_required = models.BooleanField(default=False, help_text=_("Requires special handling"))
    min_days_override = models.PositiveSmallIntegerField(null=True, blank=True)
    max_days_override = models.PositiveSmallIntegerField(null=True, blank=True)
    delivery_fee_override = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    
    # Additional Jumia-like features
    is_jumia_express = models.BooleanField(default=False, help_text=_("Delivered same day or next day"))
    is_jumia_prime = models.BooleanField(default=False, help_text=_("Available for free delivery with prime subscription"))
    
    # Product shipping dimensions and weight
    weight_kg = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True, 
                                  help_text=_("Weight in kilograms"))
    length_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                  help_text=_("Length in centimeters"))
    width_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                 help_text=_("Width in centimeters"))
    height_cm = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True,
                                  help_text=_("Height in centimeters"))
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'product_delivery_info'
        verbose_name = _('Product Delivery Information')
        verbose_name_plural = _('Product Delivery Information')
        
    def __str__(self):
        return f"Delivery info for {self.product.title}"
    
    def get_estimated_delivery_days(self, region=None):
        """Get the estimated delivery time for this product, potentially for a specific region"""
        min_days = self.min_days_override
        max_days = self.max_days_override
        
        # If product overrides not specified, use region-specific policy if available
        if region and (min_days is None or max_days is None):
            try:
                regional_policy = RegionalDeliveryPolicy.objects.get(policy=self.policy, region=region)
                min_days = min_days or regional_policy.min_days
                max_days = max_days or regional_policy.max_days
            except RegionalDeliveryPolicy.DoesNotExist:
                pass
        
        # If product or region overrides not specified, use base policy
        min_days = min_days or self.policy.min_days
        max_days = max_days or self.policy.max_days
        
        return (min_days, max_days)
    
    def get_delivery_fee(self, region=None, order_total=0):
        """Calculate delivery fee for this product, potentially for a specific region and order total"""
        # Start with product-specific override if available
        fee = self.delivery_fee_override
        
        # If not specified, use region-specific policy if available
        if fee is None and region:
            try:
                regional_policy = RegionalDeliveryPolicy.objects.get(policy=self.policy, region=region)
                fee = regional_policy.delivery_fee
            except RegionalDeliveryPolicy.DoesNotExist:
                pass
        
        # If no product or region override, use base policy fee
        fee = fee or self.policy.base_fee
        
        # Check for free delivery threshold
        if order_total >= self.policy.free_delivery_threshold and self.policy.free_delivery_threshold > 0:
            return 0
            
        return fee
