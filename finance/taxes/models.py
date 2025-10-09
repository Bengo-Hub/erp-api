from django.db import models
from django.utils.translation import gettext_lazy as _
from decimal import Decimal
from django.core.validators import MinValueValidator, MaxValueValidator
from business.models import Bussiness

class TaxCategory(models.Model):
    """Categories for different types of taxes (e.g., Sales Tax, VAT, GST)"""
    name = models.CharField(_('Name'), max_length=100)
    description = models.TextField(_('Description'), blank=True, null=True)
    business = models.ForeignKey(Bussiness, on_delete=models.CASCADE, related_name='tax_categories')
    is_active = models.BooleanField(_('Active'), default=True)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)
    
    class Meta:
        verbose_name = _('Tax Category')
        verbose_name_plural = _('Tax Categories')
        ordering = ['name']
        unique_together = [['name', 'business']]
        indexes = [
            models.Index(fields=['name'], name='idx_tax_category_name'),
            models.Index(fields=['business'], name='idx_tax_category_business'),
            models.Index(fields=['is_active'], name='idx_tax_category_active'),
            models.Index(fields=['created_at'], name='idx_tax_category_created_at'),
        ]
    
    def __str__(self):
        return self.name


class Tax(models.Model):
    """Individual tax rates that can be applied to products/services"""
    TAX_CALCULATION_TYPES = (
        ('percentage', _('Percentage')),
        ('fixed', _('Fixed Amount')),
    )
    
    name = models.CharField(_('Name'), max_length=100)
    category = models.ForeignKey(TaxCategory, on_delete=models.CASCADE, related_name='taxes')
    business = models.ForeignKey(Bussiness, on_delete=models.CASCADE, related_name='taxes')
    calculation_type = models.CharField(_('Calculation Type'), max_length=20, choices=TAX_CALCULATION_TYPES, default='percentage')
    rate = models.DecimalField(_('Rate'), max_digits=10, decimal_places=4, 
                              validators=[MinValueValidator(0), MaxValueValidator(100)],
                              help_text=_('For percentage: 0-100, for fixed amount: actual amount'))
    is_default = models.BooleanField(_('Default'), default=False)
    is_active = models.BooleanField(_('Active'), default=True)
    apply_to_shipping = models.BooleanField(_('Apply to Shipping'), default=False)
    description = models.TextField(_('Description'), blank=True, null=True)
    tax_number = models.CharField(_('Tax Registration Number'), max_length=50, blank=True, null=True)
    # KRA integration mapping
    kra_code = models.CharField(_('KRA Code'), max_length=50, blank=True, null=True, help_text=_('KRA tax code mapping'))
    kra_rate_code = models.CharField(_('KRA Rate Code'), max_length=50, blank=True, null=True)
    is_vat = models.BooleanField(_('Is VAT'), default=False)
    is_withholding = models.BooleanField(_('Is Withholding Tax'), default=False)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)
    
    class Meta:
        verbose_name = _('Tax')
        verbose_name_plural = _('Taxes')
        ordering = ['name']
        unique_together = [['name', 'business']]
        indexes = [
            models.Index(fields=['name'], name='idx_tax_name'),
            models.Index(fields=['category'], name='idx_tax_category'),
            models.Index(fields=['business'], name='idx_tax_business'),
            models.Index(fields=['calculation_type'], name='idx_tax_calc_type'),
            models.Index(fields=['is_default'], name='idx_tax_is_default'),
            models.Index(fields=['is_active'], name='idx_tax_active'),
            models.Index(fields=['tax_number'], name='idx_tax_number'),
            models.Index(fields=['kra_code'], name='idx_tax_kra_code'),
            models.Index(fields=['is_vat'], name='idx_tax_is_vat'),
            models.Index(fields=['is_withholding'], name='idx_tax_is_withholding'),
            models.Index(fields=['created_at'], name='idx_tax_created_at'),
        ]
    
    def __str__(self):
        if self.calculation_type == 'percentage':
            return f"{self.name} ({self.rate}%)"
        return f"{self.name} ({self.rate})"
    
    def save(self, *args, **kwargs):
        # If this tax is set as default, unset any other default taxes for the same business
        if self.is_default:
            Tax.objects.filter(business=self.business, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


class TaxGroup(models.Model):
    """Groups of taxes that can be applied together"""
    name = models.CharField(_('Name'), max_length=100)
    business = models.ForeignKey(Bussiness, on_delete=models.CASCADE, related_name='tax_groups')
    taxes = models.ManyToManyField(Tax, through='TaxGroupItem', related_name='tax_groups')
    is_active = models.BooleanField(_('Active'), default=True)
    description = models.TextField(_('Description'), blank=True, null=True)
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)
    
    class Meta:
        verbose_name = _('Tax Group')
        verbose_name_plural = _('Tax Groups')
        ordering = ['name']
        unique_together = [['name', 'business']]
        indexes = [
            models.Index(fields=['name'], name='idx_tax_group_name'),
            models.Index(fields=['business'], name='idx_tax_group_business'),
            models.Index(fields=['is_active'], name='idx_tax_group_active'),
            models.Index(fields=['created_at'], name='idx_tax_group_created_at'),
        ]
    
    def __str__(self):
        return self.name


class TaxGroupItem(models.Model):
    """Association between tax groups and individual taxes"""
    tax_group = models.ForeignKey(TaxGroup, on_delete=models.CASCADE, related_name='items')
    tax = models.ForeignKey(Tax, on_delete=models.CASCADE, related_name='group_items')
    order = models.PositiveIntegerField(default=0)
    
    class Meta:
        verbose_name = _('Tax Group Item')
        verbose_name_plural = _('Tax Group Items')
        ordering = ['order']
        unique_together = [['tax_group', 'tax']]
        indexes = [
            models.Index(fields=['tax_group'], name='idx_tax_grp_item_grp'),
            models.Index(fields=['tax'], name='idx_tax_grp_item_tax'),
            models.Index(fields=['order'], name='idx_tax_grp_item_order'),
        ]
    
    def __str__(self):
        return f"{self.tax_group.name} - {self.tax.name}"


class TaxPeriod(models.Model):
    """Reporting periods for tax collections and filings"""
    PERIOD_TYPES = (
        ('monthly', _('Monthly')),
        ('quarterly', _('Quarterly')),
        ('semi_annual', _('Semi-Annual')),
        ('annual', _('Annual')),
        ('custom', _('Custom')),
    )
    
    STATUS_CHOICES = (
        ('open', _('Open')),
        ('closed', _('Closed')),
        ('filed', _('Filed')),
        ('paid', _('Paid')),
    )
    
    business = models.ForeignKey(Bussiness, on_delete=models.CASCADE, related_name='tax_periods')
    name = models.CharField(_('Name'), max_length=100)
    period_type = models.CharField(_('Period Type'), max_length=20, choices=PERIOD_TYPES)
    start_date = models.DateField(_('Start Date'))
    end_date = models.DateField(_('End Date'))
    due_date = models.DateField(_('Filing Due Date'))
    status = models.CharField(_('Status'), max_length=20, choices=STATUS_CHOICES, default='open')
    notes = models.TextField(_('Notes'), blank=True, null=True)
    total_collected = models.DecimalField(_('Total Tax Collected'), max_digits=15, decimal_places=2, default=Decimal('0.00'))
    total_paid = models.DecimalField(_('Total Tax Paid'), max_digits=15, decimal_places=2, default=Decimal('0.00'))
    kra_filing_reference = models.CharField(_('KRA Filing Reference'), max_length=100, blank=True, null=True)
    filed_at = models.DateTimeField(_('Filed At'), blank=True, null=True)
    # KRA/eTIMS integration tracking
    submission_payload = models.JSONField(_('Submission Payload'), blank=True, null=True, help_text=_('Last payload submitted to KRA'))
    submission_response = models.JSONField(_('Submission Response'), blank=True, null=True, help_text=_('Last response received from KRA'))
    last_synced_at = models.DateTimeField(_('Last Synced At'), blank=True, null=True)
    sync_status = models.CharField(_('Sync Status'), max_length=20, choices=(
        ('pending', _('Pending')),
        ('synced', _('Synced')),
        ('failed', _('Failed')),
    ), default='pending')
    created_at = models.DateTimeField(_('Created At'), auto_now_add=True)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)
    
    class Meta:
        verbose_name = _('Tax Period')
        verbose_name_plural = _('Tax Periods')
        ordering = ['-start_date']
        indexes = [
            models.Index(fields=['business'], name='idx_tax_period_business'),
            models.Index(fields=['name'], name='idx_tax_period_name'),
            models.Index(fields=['period_type'], name='idx_tax_period_type'),
            models.Index(fields=['start_date'], name='idx_tax_period_start_date'),
            models.Index(fields=['end_date'], name='idx_tax_period_end_date'),
            models.Index(fields=['due_date'], name='idx_tax_period_due_date'),
            models.Index(fields=['status'], name='idx_tax_period_status'),
            models.Index(fields=['created_at'], name='idx_tax_period_created_at'),
            models.Index(fields=['last_synced_at'], name='idx_tax_period_last_synced_at'),
            models.Index(fields=['sync_status'], name='idx_tax_period_sync_status'),
        ]
    
    def __str__(self):
        return f"{self.name} ({self.start_date} to {self.end_date})"
