from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from decimal import Decimal, InvalidOperation
from business.models import Branch
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid

User = get_user_model()

class AssetCategory(models.Model):
    """Asset categories for classification"""
    name = models.CharField(_("Category Name"), max_length=100, unique=True)
    description = models.TextField(_("Description"), blank=True, null=True)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='subcategories')
    depreciation_rate = models.DecimalField(_("Default Depreciation Rate (%)"), max_digits=5, decimal_places=2, default=Decimal('0.00'),
                                          validators=[MinValueValidator(0), MaxValueValidator(100)])
    useful_life_years = models.PositiveIntegerField(_("Useful Life (Years)"), default=5)
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        if self.parent:
            return f"{self.parent.name} > {self.name}"
        return self.name

    class Meta:
        verbose_name = _("Asset Category")
        verbose_name_plural = _("Asset Categories")
        db_table = "asset_categories"
        ordering = ['name']

class Asset(models.Model):
    """Core asset model for tracking business assets"""

    ASSET_STATUS = [
        ('active', _('Active')),
        ('inactive', _('Inactive')),
        ('maintenance', _('Under Maintenance')),
        ('disposed', _('Disposed')),
        ('lost', _('Lost/Stolen')),
        ('damaged', _('Damaged')),
        ('retired', _('Retired')),
    ]

    CONDITION_STATUS = [
        ('excellent', _('Excellent')),
        ('good', _('Good')),
        ('fair', _('Fair')),
        ('poor', _('Poor')),
        ('critical', _('Critical')),
    ]

    # Basic Information
    asset_tag = models.CharField(_("Asset Tag"), max_length=50, unique=True, db_index=True)
    name = models.CharField(_("Asset Name"), max_length=200)
    description = models.TextField(_("Description"), blank=True, null=True)
    category = models.ForeignKey(AssetCategory, on_delete=models.SET_NULL, null=True, blank=True, related_name='assets')

    # Identification
    serial_number = models.CharField(_("Serial Number"), max_length=100, blank=True, null=True, db_index=True)
    model = models.CharField(_("Model"), max_length=100, blank=True, null=True)
    manufacturer = models.CharField(_("Manufacturer"), max_length=100, blank=True, null=True)
    barcode = models.CharField(_("Barcode"), max_length=100, blank=True, null=True, unique=True)

    # Financial Information
    purchase_date = models.DateField(_("Purchase Date"), null=True, blank=True)
    purchase_cost = models.DecimalField(_("Purchase Cost"), max_digits=12, decimal_places=2, default=Decimal('0.00'),
                                      validators=[MinValueValidator(0)])
    current_value = models.DecimalField(_("Current Value"), max_digits=12, decimal_places=2, default=Decimal('0.00'),
                                       validators=[MinValueValidator(0)])
    salvage_value = models.DecimalField(_("Salvage Value"), max_digits=12, decimal_places=2, default=Decimal('0.00'),
                                       validators=[MinValueValidator(0)])
    depreciation_rate = models.DecimalField(_("Depreciation Rate (%)"), max_digits=5, decimal_places=2, default=Decimal('0.00'),
                                          validators=[MinValueValidator(0), MaxValueValidator(100)])
    depreciation_method = models.CharField(_("Depreciation Method"), max_length=20, default='straight_line',
                                          choices=[('straight_line', 'Straight Line'), ('declining_balance', 'Declining Balance')])

    # Location and Assignment
    location = models.CharField(_("Location"), max_length=200, blank=True, null=True)
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='assets')
    assigned_to = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='assigned_assets')
    custodian = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='custodian_assets')

    # Status and Condition
    status = models.CharField(_("Status"), max_length=20, choices=ASSET_STATUS, default='active', db_index=True)
    condition = models.CharField(_("Condition"), max_length=20, choices=CONDITION_STATUS, blank=True, null=True)

    # Maintenance Information
    warranty_expiry = models.DateField(_("Warranty Expiry"), null=True, blank=True)
    last_maintenance = models.DateField(_("Last Maintenance"), null=True, blank=True)
    next_maintenance = models.DateField(_("Next Maintenance Due"), null=True, blank=True)
    maintenance_schedule = models.CharField(_("Maintenance Schedule"), max_length=20, blank=True, null=True,
                                           choices=[('monthly', 'Monthly'), ('quarterly', 'Quarterly'), ('yearly', 'Yearly')])

    # Insurance Information
    insurance_policy = models.CharField(_("Insurance Policy Number"), max_length=100, blank=True, null=True)
    insurance_provider = models.CharField(_("Insurance Provider"), max_length=100, blank=True, null=True)
    insurance_expiry = models.DateField(_("Insurance Expiry"), null=True, blank=True)
    insurance_value = models.DecimalField(_("Insurance Value"), max_digits=12, decimal_places=2, default=Decimal('0.00'))

    # Metadata
    notes = models.TextField(_("Notes"), blank=True, null=True)
    is_active = models.BooleanField(_("Active"), default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='created_assets')

    # Calculated Fields (updated via signals or management commands)
    accumulated_depreciation = models.DecimalField(_("Accumulated Depreciation"), max_digits=12, decimal_places=2, default=Decimal('0.00'))
    book_value = models.DecimalField(_("Book Value"), max_digits=12, decimal_places=2, default=Decimal('0.00'))

    def __str__(self):
        return f"{self.asset_tag} - {self.name}"

    def save(self, *args, **kwargs):
        if not self.asset_tag:
            # Auto-generate asset tag if not provided
            self.asset_tag = f"AST-{uuid.uuid4().hex[:8].upper()}"

        # Calculate current value if not provided
        if not self.current_value and self.purchase_cost:
            self.current_value = self.purchase_cost

        # Calculate book value - ensure proper Decimal handling
        try:
            accumulated_dep = Decimal(str(self.accumulated_depreciation)) if self.accumulated_depreciation else Decimal('0.00')
            self.book_value = self.current_value - accumulated_dep
        except (ValueError, TypeError, InvalidOperation):
            # Fallback if accumulated_depreciation is not a valid decimal
            self.book_value = self.current_value

        super().save(*args, **kwargs)

    def calculate_depreciation(self, period_months=1):
        """Calculate depreciation for a given period"""
        if not self.purchase_cost or not self.depreciation_rate:
            return Decimal('0.00')

        if self.depreciation_method == 'straight_line':
            depreciation_rate_decimal = self.depreciation_rate / Decimal('100')
            annual_depreciation = (self.purchase_cost - self.salvage_value) * depreciation_rate_decimal
            return annual_depreciation * (period_months / 12)
        else:
            # Declining balance method
            rate = self.depreciation_rate / Decimal('100')
            return self.current_value * rate * (period_months / 12)

    def get_depreciation_schedule(self, years=None):
        """Get depreciation schedule for the asset"""
        if not years:
            years = self.category.useful_life_years if self.category else 5

        schedule = []
        current_value = self.purchase_cost
        accumulated = Decimal('0.00')

        for year in range(1, years + 1):
            depreciation = self.calculate_depreciation(12)
            accumulated += depreciation
            current_value -= depreciation

            schedule.append({
                'year': year,
                'depreciation': depreciation,
                'accumulated_depreciation': accumulated,
                'book_value': current_value
            })

        return schedule

    class Meta:
        verbose_name = _("Asset")
        verbose_name_plural = _("Assets")
        db_table = "assets"
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['asset_tag'], name='idx_assets_asset_tag'),
            models.Index(fields=['category'], name='idx_assets_category'),
            models.Index(fields=['status'], name='idx_assets_status'),
            models.Index(fields=['branch'], name='idx_assets_branch'),
            models.Index(fields=['assigned_to'], name='idx_assets_assigned_to'),
            models.Index(fields=['custodian'], name='idx_assets_custodian'),
            models.Index(fields=['serial_number'], name='idx_assets_serial'),
            models.Index(fields=['barcode'], name='idx_assets_barcode'),
            models.Index(fields=['purchase_date'], name='idx_assets_purchase_date'),
            models.Index(fields=['warranty_expiry'], name='idx_assets_warranty'),
            models.Index(fields=['next_maintenance'], name='idx_assets_next_maint'),
        ]

class AssetDepreciation(models.Model):
    """Track depreciation history for assets"""
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='depreciation_records')
    period_start = models.DateField(_("Period Start"))
    period_end = models.DateField(_("Period End"))
    depreciation_amount = models.DecimalField(_("Depreciation Amount"), max_digits=12, decimal_places=2)
    accumulated_depreciation = models.DecimalField(_("Accumulated Depreciation"), max_digits=12, decimal_places=2)
    book_value = models.DecimalField(_("Book Value"), max_digits=12, decimal_places=2)
    posted_to_finance = models.BooleanField(_("Posted to Finance"), default=False)
    finance_transaction = models.CharField(_("Finance Transaction ID"), max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.asset.asset_tag} - {self.period_start} to {self.period_end}"

    class Meta:
        verbose_name = _("Asset Depreciation")
        verbose_name_plural = _("Asset Depreciation")
        db_table = "asset_depreciation"
        ordering = ['-period_start']
        unique_together = ['asset', 'period_start']

class AssetInsurance(models.Model):
    """Track insurance policies for assets"""
    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='insurance_policies')
    policy_number = models.CharField(_("Policy Number"), max_length=100, unique=True)
    provider = models.CharField(_("Insurance Provider"), max_length=100)
    policy_type = models.CharField(_("Policy Type"), max_length=50)
    coverage_amount = models.DecimalField(_("Coverage Amount"), max_digits=12, decimal_places=2)
    premium_amount = models.DecimalField(_("Premium Amount"), max_digits=10, decimal_places=2)
    start_date = models.DateField(_("Start Date"))
    end_date = models.DateField(_("End Date"))
    deductible = models.DecimalField(_("Deductible"), max_digits=10, decimal_places=2, default=Decimal('0.00'))
    is_active = models.BooleanField(_("Active"), default=True)
    notes = models.TextField(_("Notes"), blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.policy_number} - {self.asset.asset_tag}"

    class Meta:
        verbose_name = _("Asset Insurance")
        verbose_name_plural = _("Asset Insurance")
        db_table = "asset_insurance"
        ordering = ['-start_date']

class AssetAudit(models.Model):
    """Track physical audits and verifications of assets"""
    AUDIT_STATUS = [
        ('planned', _('Planned')),
        ('in_progress', _('In Progress')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='audits')
    audit_date = models.DateField(_("Audit Date"))
    auditor = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    status = models.CharField(_("Status"), max_length=20, choices=AUDIT_STATUS, default='planned')
    location_verified = models.CharField(_("Location Verified"), max_length=200, blank=True, null=True)
    condition_verified = models.CharField(_("Condition Verified"), max_length=20, blank=True, null=True)
    custodian_verified = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='verified_audits')
    discrepancies = models.TextField(_("Discrepancies"), blank=True, null=True)
    recommendations = models.TextField(_("Recommendations"), blank=True, null=True)
    next_audit_date = models.DateField(_("Next Audit Date"), null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Audit: {self.asset.asset_tag} - {self.audit_date}"

    class Meta:
        verbose_name = _("Asset Audit")
        verbose_name_plural = _("Asset Audits")
        db_table = "asset_audits"
        ordering = ['-audit_date']

class AssetReservation(models.Model):
    """Track asset reservations/bookings"""
    RESERVATION_STATUS = [
        ('pending', _('Pending')),
        ('approved', _('Approved')),
        ('active', _('Active')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='reservations')
    reserved_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name='asset_reservations')
    start_date = models.DateTimeField(_("Start Date"))
    end_date = models.DateTimeField(_("End Date"))
    purpose = models.TextField(_("Purpose"))
    status = models.CharField(_("Status"), max_length=20, choices=RESERVATION_STATUS, default='pending')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    notes = models.TextField(_("Notes"), blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Reservation: {self.asset.asset_tag} - {self.reserved_by.get_full_name()}"

    def save(self, *args, **kwargs):
        # Validate reservation dates
        if self.start_date >= self.end_date:
            raise ValueError("Start date must be before end date")
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Asset Reservation")
        verbose_name_plural = _("Asset Reservations")
        db_table = "asset_reservations"
        ordering = ['-created_at']

class AssetTransfer(models.Model):
    """Track asset transfers between locations/users"""

    TRANSFER_STATUS = [
        ('pending', _('Pending')),
        ('approved', _('Approved')),
        ('in_transit', _('In Transit')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='transfers')
    from_location = models.CharField(_("From Location"), max_length=200)
    to_location = models.CharField(_("To Location"), max_length=200)
    from_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_from')
    to_user = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='transfers_to')
    transfer_date = models.DateTimeField(_("Transfer Date"), default=timezone.now)
    scheduled_date = models.DateTimeField(_("Scheduled Date"), null=True, blank=True)
    status = models.CharField(_("Status"), max_length=20, choices=TRANSFER_STATUS, default='pending')
    reason = models.TextField(_("Transfer Reason"), blank=True, null=True)
    transferred_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='asset_transfers_made')
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_transfers')
    notes = models.TextField(_("Notes"), blank=True, null=True)
    tracking_number = models.CharField(_("Tracking Number"), max_length=100, blank=True, null=True)

    def __str__(self):
        return f"Transfer: {self.asset.asset_tag} from {self.from_location} to {self.to_location}"

    def save(self, *args, **kwargs):
        if self.status == 'completed' and self.asset:
            # Update asset location and custodian when transfer is completed
            self.asset.location = self.to_location
            if self.to_user:
                self.asset.custodian = self.to_user
            self.asset.save(update_fields=['location', 'custodian'])
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Asset Transfer")
        verbose_name_plural = _("Asset Transfers")
        db_table = "asset_transfers"
        ordering = ['-transfer_date']

class AssetMaintenance(models.Model):
    """Track asset maintenance activities"""

    MAINTENANCE_TYPE = [
        ('preventive', _('Preventive')),
        ('corrective', _('Corrective')),
        ('emergency', _('Emergency')),
        ('predictive', _('Predictive')),
        ('condition_based', _('Condition Based')),
    ]

    MAINTENANCE_STATUS = [
        ('scheduled', _('Scheduled')),
        ('in_progress', _('In Progress')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
        ('deferred', _('Deferred')),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='maintenance_records')
    maintenance_type = models.CharField(_("Maintenance Type"), max_length=20, choices=MAINTENANCE_TYPE)
    scheduled_date = models.DateField(_("Scheduled Date"))
    completed_date = models.DateField(_("Completed Date"), null=True, blank=True)
    performed_by = models.CharField(_("Performed By"), max_length=100)
    cost = models.DecimalField(_("Cost"), max_digits=10, decimal_places=2, default=Decimal('0.00'))
    description = models.TextField(_("Description"))
    findings = models.TextField(_("Findings"), blank=True, null=True)
    recommendations = models.TextField(_("Recommendations"), blank=True, null=True)
    next_maintenance_date = models.DateField(_("Next Maintenance"), null=True, blank=True)
    status = models.CharField(_("Status"), max_length=20, choices=MAINTENANCE_STATUS, default='scheduled')
    priority = models.CharField(_("Priority"), max_length=20, default='medium',
                               choices=[('low', 'Low'), ('medium', 'Medium'), ('high', 'High'), ('critical', 'Critical')])
    downtime_hours = models.DecimalField(_("Downtime (Hours)"), max_digits=8, decimal_places=2, default=Decimal('0.00'))

    def __str__(self):
        return f"Maintenance: {self.asset.asset_tag} - {self.maintenance_type}"

    def save(self, *args, **kwargs):
        if self.completed_date and not self.asset.last_maintenance:
            self.asset.last_maintenance = self.completed_date
        if self.next_maintenance_date:
            self.asset.next_maintenance = self.next_maintenance_date
        super().save(*args, **kwargs)
        if self.asset:
            # Only save specific fields to avoid unnecessary calculations
            self.asset.save(update_fields=['last_maintenance', 'next_maintenance'])

    class Meta:
        verbose_name = _("Asset Maintenance")
        verbose_name_plural = _("Asset Maintenance")
        ordering = ['-scheduled_date']

class AssetDisposal(models.Model):
    """Track asset disposals"""

    DISPOSAL_METHOD = [
        ('sold', _('Sold')),
        ('scrapped', _('Scrapped')),
        ('donated', _('Donated')),
        ('stolen', _('Stolen/Lost')),
        ('returned', _('Returned to Supplier')),
        ('recycled', _('Recycled')),
        ('destroyed', _('Destroyed')),
    ]

    DISPOSAL_STATUS = [
        ('pending', _('Pending Approval')),
        ('approved', _('Approved')),
        ('rejected', _('Rejected')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
    ]

    asset = models.ForeignKey(Asset, on_delete=models.CASCADE, related_name='disposals')
    disposal_date = models.DateField(_("Disposal Date"))
    disposal_method = models.CharField(_("Disposal Method"), max_length=20, choices=DISPOSAL_METHOD)
    disposal_value = models.DecimalField(_("Disposal Value"), max_digits=10, decimal_places=2, default=Decimal('0.00'))
    reason = models.TextField(_("Reason for Disposal"))
    approved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_disposals')
    status = models.CharField(_("Status"), max_length=20, choices=DISPOSAL_STATUS, default='pending')
    notes = models.TextField(_("Notes"), blank=True, null=True)
    disposal_certificate = models.CharField(_("Disposal Certificate"), max_length=100, blank=True, null=True)

    def __str__(self):
        return f"Disposal: {self.asset.asset_tag} - {self.disposal_method}"

    def save(self, *args, **kwargs):
        if self.status == 'completed' and self.asset:
            # Update asset status when disposal is completed
            self.asset.status = 'disposed'
            self.asset.current_value = Decimal('0.00')
            self.asset.save()
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = _("Asset Disposal")
        verbose_name_plural = _("Asset Disposals")
        db_table = "asset_disposals"
        ordering = ['-disposal_date']
