from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _
from ecommerce.product.models import Products
from ecommerce.stockinventory.models import StockInventory, Unit
from business.models import Branch
from django.utils import timezone
import uuid
from django.db.models import Sum
from decimal import Decimal

User = get_user_model()

class RawMaterialUsage(models.Model):
    TRANSACTION_TYPES = [
    ('production', 'Production'),
    ('testing', 'Testing'),
    ('wastage', 'Wastage'),
    ('return', 'Return'),
    ('adjustment', 'Adjustment')
    ]
    finished_product = models.ForeignKey(Products, on_delete=models.CASCADE, related_name='raw_material_usages')
    raw_material = models.ForeignKey(StockInventory, on_delete=models.CASCADE, related_name='used_in_products')
    quantity_used = models.DecimalField(max_digits=14, decimal_places=4, default=Decimal('0.0000'))
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    transaction_date = models.DateTimeField(auto_now_add=True)
    notes = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.raw_material} used in {self.finished_product} - Qty: {self.quantity_used}"

    class Meta:
        verbose_name = "Raw Material Usage"
        verbose_name_plural = "Raw Material Usages"
        unique_together = ('finished_product', 'raw_material', 'transaction_date')
        indexes = [
            models.Index(fields=['finished_product'], name='idx_raw_mat_usage_finished'),
            models.Index(fields=['raw_material'], name='idx_raw_mat_usage_raw_mat'),
            models.Index(fields=['transaction_type'], name='idx_raw_mat_usage_txn_type'),
            models.Index(fields=['transaction_date'], name='idx_raw_mat_usage_txn_date'),
            models.Index(fields=['created_at'], name='idx_raw_mat_usage_created'),
        ]

class ProductFormula(models.Model):
    """
    A formula for manufacturing a product from raw materials.
    """
    name = models.CharField(_("Formula Name"), max_length=255)
    description = models.TextField(_("Description"), blank=True, null=True)
    final_product = models.ForeignKey(
        Products, 
        on_delete=models.CASCADE, 
        related_name="formulas",
        help_text=_("The final product that this formula produces")
    )
    expected_output_quantity = models.DecimalField(
        _("Expected Output Quantity"), 
        max_digits=14, 
        decimal_places=4,
        help_text=_("The expected quantity of final product produced by this formula")
    )
    output_unit = models.ForeignKey(
        Unit, 
        on_delete=models.SET_NULL, 
        related_name="product_formulas", 
        null=True
    )
    is_active = models.BooleanField(_("Active"), default=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        related_name="product_formulas",
        null=True
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    version = models.PositiveIntegerField(_("Version"), default=1)
    
    def __str__(self):
        return f"{self.name} - v{self.version}"
    
    class Meta:
        verbose_name = _("Product Formula")
        verbose_name_plural = _("Product Formulas")
        unique_together = ('name', 'version')
        ordering = ['-updated_at']
        indexes = [
            models.Index(fields=['name'], name='idx_product_formula_name'),
            models.Index(fields=['final_product'], name='idx_product_formula_final_prod'),
            models.Index(fields=['is_active'], name='idx_product_formula_is_active'),
            models.Index(fields=['created_by'], name='idx_product_formula_created_by'),
            models.Index(fields=['created_at'], name='idx_product_formula_created_at'),
            models.Index(fields=['updated_at'], name='idx_product_formula_updated_at'),
            models.Index(fields=['version'], name='idx_product_formula_version'),
        ]
    
    def get_raw_material_cost(self):
        """Calculate the total cost of raw materials for this formula"""
        total_cost = sum(
            ingredient.raw_material.buying_price * ingredient.quantity 
            for ingredient in self.ingredients.all()
        )
        return total_cost
    
    def get_suggested_selling_price(self, markup_percentage=30):
        """
        Calculate suggested selling price based on raw materials cost and markup
        """
        raw_cost = self.get_raw_material_cost()
        return raw_cost * (1 + Decimal(markup_percentage) / 100)
    
    def clone_for_new_version(self):
        """Create a new version of this formula"""
        new_version = self.version + 1
        new_formula = ProductFormula.objects.create(
            name=self.name,
            description=f"{self.description}\n(Cloned from v{self.version})",
            final_product=self.final_product,
            expected_output_quantity=self.expected_output_quantity,
            output_unit=self.output_unit,
            is_active=True,
            created_by=self.created_by,
            version=new_version
        )
        
        # Clone all ingredients
        for ingredient in self.ingredients.all():
            FormulaIngredient.objects.create(
                formula=new_formula,
                raw_material=ingredient.raw_material,
                quantity=ingredient.quantity,
                unit=ingredient.unit,
                notes=ingredient.notes
            )
        
        # Deactivate the old formula
        self.is_active = False
        self.save()
        
        return new_formula


class FormulaIngredient(models.Model):
    """
    An ingredient in a product formula.
    """
    formula = models.ForeignKey(
        ProductFormula, 
        on_delete=models.CASCADE, 
        related_name="ingredients"
    )
    raw_material = models.ForeignKey(
        StockInventory, 
        on_delete=models.CASCADE, 
        related_name="formula_usages"
    )
    quantity = models.DecimalField(_("Quantity"), max_digits=14, decimal_places=4)
    unit = models.ForeignKey(
        Unit, 
        on_delete=models.SET_NULL, 
        related_name="formula_ingredients", 
        null=True
    )
    notes = models.TextField(_("Notes"), blank=True, null=True)
    
    def __str__(self):
        return f"{self.raw_material.product.title} - {self.quantity} {self.unit}"
    
    class Meta:
        verbose_name = _("Formula Ingredient")
        verbose_name_plural = _("Formula Ingredients")
        unique_together = ('formula', 'raw_material')
        indexes = [
            models.Index(fields=['formula'], name='idx_formula_ingredient_formula'),
            models.Index(fields=['raw_material'], name='idx_formula_ingredient_raw_mat'),
            models.Index(fields=['unit'], name='idx_formula_ingredient_unit'),
        ]


class ProductionBatch(models.Model):
    """
    A batch of products manufactured from a formula.
    """
    STATUS_CHOICES = [
        ('planned', _('Planned')),
        ('in_progress', _('In Progress')),
        ('completed', _('Completed')),
        ('cancelled', _('Cancelled')),
        ('failed', _('Failed')),
    ]
    
    batch_number = models.CharField(_("Batch Number"), max_length=50, unique=True)
    formula = models.ForeignKey(
        ProductFormula, 
        on_delete=models.CASCADE, 
        related_name="production_batches"
    )
    branch = models.ForeignKey(
        Branch,
        on_delete=models.CASCADE,
        related_name="production_batches"
    )
    scheduled_date = models.DateTimeField(_("Scheduled Date"))
    start_date = models.DateTimeField(_("Start Date"), null=True, blank=True)
    end_date = models.DateTimeField(_("End Date"), null=True, blank=True)
    status = models.CharField(
        _("Status"), 
        max_length=20, 
        choices=STATUS_CHOICES, 
        default='planned'
    )
    planned_quantity = models.DecimalField(
        _("Planned Quantity"), 
        max_digits=14, 
        decimal_places=4
    )
    actual_quantity = models.DecimalField(
        _("Actual Quantity"), 
        max_digits=14, 
        decimal_places=4, 
        null=True, 
        blank=True
    )
    labor_cost = models.DecimalField(
        _("Labor Cost"), 
        max_digits=14, 
        decimal_places=4, 
        default=Decimal('0.0000')
    )
    overhead_cost = models.DecimalField(
        _("Overhead Cost"), 
        max_digits=14, 
        decimal_places=4, 
        default=Decimal('0.0000')
    )
    notes = models.TextField(_("Notes"), blank=True, null=True)
    created_by = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        related_name="created_batches",
        null=True
    )
    supervisor = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        related_name="supervised_batches",
        null=True, 
        blank=True
    )
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    updated_at = models.DateTimeField(_("Updated At"), auto_now=True)
    
    def __str__(self):
        return f"Batch #{self.batch_number} - {self.formula.name} ({self.status})"
    
    class Meta:
        verbose_name = _("Production Batch")
        verbose_name_plural = _("Production Batches")
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['batch_number'], name='idx_prod_batch_number'),
            models.Index(fields=['formula'], name='idx_production_batch_formula'),
            models.Index(fields=['branch'], name='idx_production_batch_branch'),
            models.Index(fields=['scheduled_date'], name='idx_prod_batch_scheduled'),
            models.Index(fields=['start_date'], name='idx_prod_batch_start'),
            models.Index(fields=['end_date'], name='idx_prod_batch_end'),
            models.Index(fields=['status'], name='idx_prod_batch_status'),
            models.Index(fields=['created_by'], name='idx_prod_batch_created_by'),
            models.Index(fields=['supervisor'], name='idx_prod_batch_supervisor'),
            models.Index(fields=['created_at'], name='idx_prod_batch_created'),
            models.Index(fields=['updated_at'], name='idx_prod_batch_updated'),
        ]
    
    def save(self, *args, **kwargs):
        # Generate batch number if it doesn't exist
        if not self.batch_number:
            prefix = 'BATCH'
            date_str = timezone.now().strftime('%y%m%d')
            random_str = str(uuid.uuid4().int)[:6]
            self.batch_number = f"{prefix}-{date_str}-{random_str}"
        
        # Update timestamps
        if self.status == 'in_progress' and not self.start_date:
            self.start_date = timezone.now()
        if self.status in ['completed', 'failed'] and not self.end_date:
            self.end_date = timezone.now()
            
        super().save(*args, **kwargs)
    
    def get_raw_material_cost(self):
        """Calculate the total cost of raw materials used in this batch"""
        return sum(material.cost for material in self.raw_materials.all())
    
    def get_total_cost(self):
        """Calculate the total cost of the batch including labor and overhead"""
        return self.get_raw_material_cost() + self.labor_cost + self.overhead_cost
    
    def get_unit_cost(self):
        """Calculate the unit cost of the product"""
        if not self.actual_quantity or self.actual_quantity == 0:
            return 0
        return self.get_total_cost() / self.actual_quantity
    
    def suggested_selling_price(self, markup_percentage=30):
        """
        Calculate suggested selling price based on unit cost and markup
        """
        markup_percentage = self.branch.business.default_profit_margin
        if markup_percentage is None:
            markup_percentage = 30
        unit_cost = self.get_unit_cost()
        return unit_cost * (1 + Decimal(markup_percentage) / 100)
    
    def check_material_availability(self):
        """Check if all raw materials are available in sufficient quantity"""
        formula = self.formula
        batch_ratio = self.planned_quantity / formula.expected_output_quantity
        
        missing_materials = []
        for ingredient in formula.ingredients.all():
            required_quantity = ingredient.quantity * batch_ratio
            stock_level = ingredient.raw_material.stock_level
            
            if stock_level < required_quantity:
                missing_materials.append({
                    'material': ingredient.raw_material,
                    'required': required_quantity,
                    'available': stock_level,
                    'shortage': required_quantity - stock_level
                })
        
        return missing_materials
    
    def start_production(self):
        """Start the production process"""
        missing_materials = self.check_material_availability()
        if missing_materials:
            materials_list = ", ".join([f"{item['material']} (short by {item['shortage']})" for item in missing_materials])
            raise ValueError(f"Cannot start production due to insufficient materials: {materials_list}")
        
        self.status = 'in_progress'
        self.start_date = timezone.now()
        self.save()
        
        # Reserve materials
        formula = self.formula
        batch_ratio = Decimal(self.planned_quantity) / Decimal(formula.expected_output_quantity)
        
        for ingredient in formula.ingredients.all():
            required_quantity = ingredient.quantity * batch_ratio
            
            # Create batch material record
            BatchRawMaterial.objects.create(
                batch=self,
                raw_material=ingredient.raw_material,
                planned_quantity=required_quantity,
                unit=ingredient.unit,
                cost=ingredient.raw_material.buying_price * required_quantity
            )
            
            # Update inventory
            ingredient.raw_material.stock_level -= required_quantity
            ingredient.raw_material.save()
    
    def complete_production(self, actual_quantity):
        """Complete the production process"""
        if self.status != 'in_progress':
            raise ValueError("Cannot complete a batch that is not in progress")
        
        self.status = 'completed'
        self.actual_quantity = actual_quantity
        self.end_date = timezone.now()
        self.save()
        
        # Update raw material actual usage
        for batch_material in self.raw_materials.all():
            batch_material.actual_quantity = batch_material.planned_quantity
            batch_material.save()
        
        # get final product
        final_product = self.formula.final_product
        final_product.save()
        
        # Create usage records
        for batch_material in self.raw_materials.all():            
            RawMaterialUsage.objects.create(
                finished_product=final_product,
                raw_material=batch_material.raw_material,
                quantity_used=batch_material.actual_quantity,
                transaction_type='production',
                notes=f"Used in Batch #{self.batch_number}"
            )
    
    def cancel_production(self, reason=""):
        """Cancel the production batch"""
        old_status = self.status
        self.status = 'cancelled'
        self.notes = (self.notes or "") + f"\nCancelled reason: {reason}\n"
        self.save()
        
        # If production was in progress, return materials to inventory
        if old_status == 'in_progress':
            for batch_material in self.raw_materials.all():
                batch_material.raw_material.stock_level += batch_material.planned_quantity
                batch_material.raw_material.save()


class BatchRawMaterial(models.Model):
    """
    Raw materials used in a production batch.
    """
    batch = models.ForeignKey(
        ProductionBatch, 
        on_delete=models.CASCADE, 
        related_name="raw_materials"
    )
    raw_material = models.ForeignKey(
        StockInventory, 
        on_delete=models.CASCADE, 
        related_name="batch_usages"
    )
    planned_quantity = models.DecimalField(
        _("Planned Quantity"), 
        max_digits=14, 
        decimal_places=4
    )
    actual_quantity = models.DecimalField(
        _("Actual Quantity"), 
        max_digits=14, 
        decimal_places=4, 
        null=True, 
        blank=True
    )
    unit = models.ForeignKey(
        Unit, 
        on_delete=models.SET_NULL, 
        related_name="batch_materials", 
        null=True
    )
    cost = models.DecimalField(_("Cost"), max_digits=14, decimal_places=4)
    notes = models.TextField(_("Notes"), blank=True, null=True)
    
    def __str__(self):
        return f"{self.raw_material.product.title} - {self.planned_quantity} {self.unit}"
    
    class Meta:
        verbose_name = _("Batch Raw Material")
        verbose_name_plural = _("Batch Raw Materials")
        unique_together = ('batch', 'raw_material')
        indexes = [
            models.Index(fields=['batch'], name='idx_batch_raw_material_batch'),
            models.Index(fields=['raw_material'], name='idx_batch_raw_mat_raw_mat'),
            models.Index(fields=['unit'], name='idx_batch_raw_material_unit'),
        ]


class QualityCheck(models.Model):
    """
    Quality check for a production batch.
    """
    RESULT_CHOICES = [
        ('pass', _('Pass')),
        ('fail', _('Fail')),
        ('pending', _('Pending')),
    ]
    
    batch = models.ForeignKey(
        ProductionBatch, 
        on_delete=models.CASCADE, 
        related_name="quality_checks"
    )
    check_date = models.DateTimeField(_("Check Date"), default=timezone.now)
    inspector = models.ForeignKey(
        User, 
        on_delete=models.SET_NULL, 
        related_name="quality_checks",
        null=True
    )
    result = models.CharField(
        _("Result"), 
        max_length=10, 
        choices=RESULT_CHOICES, 
        default='pending'
    )
    notes = models.TextField(_("Notes"), blank=True, null=True)
    created_at = models.DateTimeField(_("Created At"), auto_now_add=True)
    
    def __str__(self):
        return f"QC for Batch #{self.batch.batch_number} - {self.result}"
    
    class Meta:
        verbose_name = _("Quality Check")
        verbose_name_plural = _("Quality Checks")
        ordering = ['-check_date']
        indexes = [
            models.Index(fields=['batch'], name='idx_quality_check_batch'),
            models.Index(fields=['check_date'], name='idx_quality_check_check_date'),
            models.Index(fields=['inspector'], name='idx_quality_check_inspector'),
            models.Index(fields=['result'], name='idx_quality_check_result'),
            models.Index(fields=['created_at'], name='idx_quality_check_created_at'),
        ]


class ManufacturingAnalytics(models.Model):
    """
    Analytics for manufacturing operations.
    This model stores pre-calculated analytics to improve performance.
    """
    date = models.DateField(_("Date"), unique=True)
    total_batches = models.IntegerField(_("Total Batches"), default=0)
    completed_batches = models.IntegerField(_("Completed Batches"), default=0)
    failed_batches = models.IntegerField(_("Failed Batches"), default=0)
    total_production_quantity = models.DecimalField(
        _("Total Production Quantity"), 
        max_digits=14, 
        decimal_places=4, 
        default=0
    )
    total_raw_material_cost = models.DecimalField(
        _("Total Raw Material Cost"), 
        max_digits=14, 
        decimal_places=4, 
        default=0
    )
    total_labor_cost = models.DecimalField(
        _("Total Labor Cost"), 
        max_digits=14, 
        decimal_places=4, 
        default=0
    )
    total_overhead_cost = models.DecimalField(
        _("Total Overhead Cost"), 
        max_digits=14, 
        decimal_places=4, 
        default=0
    )
    
    def __str__(self):
        return f"Manufacturing Analytics for {self.date}"
    
    class Meta:
        verbose_name = _("Manufacturing Analytics")
        verbose_name_plural = _("Manufacturing Analytics")
        ordering = ['-date']
        indexes = [
            models.Index(fields=['date'], name='idx_manuf_analytics_date'),
        ]
    
    @classmethod
    def update_for_date(cls, date):
        """Update analytics for a specific date"""
        date_start = timezone.datetime.combine(date, timezone.datetime.min.time())
        date_end = timezone.datetime.combine(date, timezone.datetime.max.time())
        
        batches = ProductionBatch.objects.filter(
            created_at__range=(date_start, date_end)
        )
        
        analytics, created = cls.objects.get_or_create(date=date)
        analytics.total_batches = batches.count()
        analytics.completed_batches = batches.filter(status='completed').count()
        analytics.failed_batches = batches.filter(status='failed').count()
        
        completed_batches = batches.filter(status='completed')
        analytics.total_production_quantity = completed_batches.aggregate(
            total=Sum('actual_quantity')
        )['total'] or 0
        
        analytics.total_raw_material_cost = sum(
            batch.get_raw_material_cost() for batch in completed_batches
        )
        analytics.total_labor_cost = completed_batches.aggregate(
            total=Sum('labor_cost')
        )['total'] or 0
        analytics.total_overhead_cost = completed_batches.aggregate(
            total=Sum('overhead_cost')
        )['total'] or 0
        
        analytics.save()
        return analytics
