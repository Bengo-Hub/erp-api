from collections.abc import Iterable
from decimal import Decimal
from django.db import models
from ecommerce.product.models import Products
from crm.contacts.models import Contact
from django.contrib.auth import get_user_model
from datetime import datetime, timedelta
from django.db import transaction
from business.models import Branch,TaxRates
from .functions import generate_ref_no
from django.db.models import F,Sum
from django.utils.translation import gettext_lazy as _

# Create your models here.
User=get_user_model()

class Unit(models.Model):
    title = models.CharField(max_length=50)

    def __str__(self):
        return self.title

    class Meta:
        db_table = "units"
        managed = True
        verbose_name_plural = "Units"
        indexes = [
            models.Index(fields=['title'], name='idx_units_title'),
        ]

class Discounts(models.Model):
    discount_types=[
        ("Fixed","Fixed"),
        ("Percentage","Percentage"),
    ]
    name=models.CharField(max_length=255)
    discount_type=models.CharField(max_length=100,choices=discount_types,default="Fixed")   
    discount_amount=models.DecimalField(max_digits=10,decimal_places=2)
    percentage=models.DecimalField(max_digits=5, decimal_places=2, default=Decimal('0.00'), help_text="Discount percentage value")
    start_date=models.DateField()
    end_date=models.DateField()
    priority=models.IntegerField(default=1)
    is_active=models.BooleanField(default=True)

    def __str__(self):
        return self.name

    class Meta:
        db_table = 'discounts'
        managed = True
        verbose_name = 'Discounts'
        verbose_name_plural = 'Discounts'
        indexes = [
            models.Index(fields=['name'], name='idx_discounts_name'),
            models.Index(fields=['discount_type'], name='idx_discounts_type'),
            models.Index(fields=['is_active'], name='idx_discounts_active'),
            models.Index(fields=['start_date'], name='idx_discounts_start_date'),
            models.Index(fields=['end_date'], name='idx_discounts_end_date'),
        ]
        
    def save(self, *args, **kwargs):
        #set start date and end date if not provided
        if self.start_date is None:
            self.start_date = datetime.now().date()
        if self.end_date is None: # set end date 30 days from start date
            self.end_date = self.start_date + timedelta(days=30)
        super(Discounts, self).save(*args, **kwargs)

class VariationImages(models.Model):
    variation_value=models.ForeignKey("Variations",on_delete=models.SET_NULL,related_name='images',null=True,blank=True)
    image = models.FileField(upload_to="products/variations/%Y%m%d/")

    def __str__(self):
        return self.image.url if self.image else None

    class Meta:
        db_table = "variationimages"
        managed = True
        verbose_name_plural = "Variation Images"
        indexes = [
            models.Index(fields=['variation_value'], name='idx_variation_images_variation'),
        ]

class Warranties(models.Model):
    name=models.CharField(max_length=255)
    duration=models.IntegerField(default=6)
    duration_period=models.CharField(max_length=255,choices=[("Days","Days"),("Months","Months"),("Years","Years")])
    description=models.TextField(help_text="Enter product IMEI, Serial here")

    def __str__(self):
        return f"{self.name} - {self.duration} {self.duration_period}"

    class Meta:
        db_table = "warranties"
        managed = True
        verbose_name_plural = "Warranties"
        indexes = [
            models.Index(fields=['name'], name='idx_warranties_name'),
            models.Index(fields=['duration'], name='idx_warranties_duration'),
        ]

class Variations(models.Model):
    stock_item = models.ForeignKey(
        "StockInventory", 
        on_delete=models.SET_NULL, 
        blank=True, 
        null=True, 
        related_name="variations"
    )
    title = models.CharField(max_length=255)
    serial = models.CharField(max_length=100, blank=True, null=True, unique=True)
    sku = models.CharField(max_length=100, default='10011', unique=True, blank=True, null=True)

    def __str__(self):
        return f"{self.title}"

    class Meta:
        managed = True
        verbose_name_plural = "Variations"
        indexes = [
            models.Index(fields=['stock_item'], name='idx_variations_stock_item'),
            models.Index(fields=['title'], name='idx_variations_title'),
            models.Index(fields=['serial'], name='idx_variations_serial'),
            models.Index(fields=['sku'], name='idx_variations_sku'),
        ]

class StockInventory(models.Model):
    PRODUCT_TYPES=[
        ("single","single"),
        ("variable","variable"),
        ("combo","combo"),
    ]
    selling_taxes=[
        ("None","None"),
        ("Inclusive","Inclusive"),
        ("Exclusive","Exclusive"),
    ]
    product = models.ForeignKey(Products, on_delete=models.CASCADE,related_name="stock")
    product_type=models.CharField(max_length=100,choices=PRODUCT_TYPES,default="single")
    variation=models.ForeignKey(Variations,on_delete=models.CASCADE,related_name='stock',blank=True,null=True)
    warranty=models.ForeignKey(Warranties,on_delete=models.SET_NULL,related_name='stock',null=True,blank=True)
    discount=models.ForeignKey("Discounts",on_delete=models.SET_NULL,related_name="stock",null=True,blank=True)
    applicable_tax=models.ForeignKey(TaxRates,on_delete=models.SET_NULL,null=True,blank=True,default=None)
    buying_price=models.DecimalField(max_digits=14,decimal_places=4,default=Decimal('0.00'))
    selling_price=models.DecimalField(max_digits=14,decimal_places=4,default=Decimal('0.00'))#view_discounts
    profit_margin=models.DecimalField(max_digits=14,decimal_places=4,default=Decimal('0.00'))
    manufacturing_cost=models.DecimalField(max_digits=14,decimal_places=4,default=Decimal('0.00'))
    stock_level = models.IntegerField(default=1)
    reorder_level = models.PositiveIntegerField(default=2)
    unit = models.ForeignKey(Unit,on_delete=models.SET_NULL,blank=True, null=True)
    branch=models.ForeignKey(Branch,on_delete=models.CASCADE,blank=True,null=True,related_name="stock")
    usage = models.CharField(max_length=20,choices=(("EX-UK","EX-UK"),("Refurbished","Refurbished"),("Used Like New","Used Like New"),("Secod Hand","Second Hand"),("New","New")),default="New",blank=True,null=True,help_text='Leave blank if not applicable')
    supplier=models.ForeignKey(Contact,on_delete=models.CASCADE,related_name='stock',null=True,blank=True)
    availability = models.CharField(max_length=20,choices=(("In Stock","In Stock"),("Out of Stock","Out of Stock"),("Re-Order","Re-Order")),default="In Stock")
    is_new_arrival = models.BooleanField(default=False)
    is_top_pick= models.BooleanField(default=False)
    is_raw_material=models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    delete_status=models.BooleanField(default=False)

    def save(self,*args,**kwargs):
        # First check if this is a new object without a primary key
        is_new = self.pk is None
        # set default unit if not set
        if self.unit is None:
            default_unit=self.branch.business.productsettings.first().default_unit or None
            if default_unit is None:
                default_unit="Piece(s)"
            self.unit = Unit.objects.get_or_create(title=default_unit)[0]
        #set default discount
        if self.discount is None:
            salesettings=self.branch.business.salesettings.first()
            if salesettings is not None:
               self.discount = Discounts.objects.get_or_create(name="Default Sale Discount",discount_amount=Decimal(salesettings.default_discount))[0]
               self.applicable_tax=salesettings.default_tax if salesettings.default_tax is not None else None
        # set selling price based on margin if not set
        if self.selling_price is None or self.selling_price == 0:
           self.selling_price = self.suggest_selling_price(30)
        if is_new:
            # Just do a normal save for new objects
            super(StockInventory,self).save(*args,**kwargs)
        else:
            # For existing objects, we can safely check relationships
            self.profit_margin=self.selling_price-self.manufacturing_cost
            super(StockInventory,self).save(*args,**kwargs)

    def create_stock_transaction(self, transaction_type, quantity, notes=None):
        """
        Create a stock transaction for this inventory item.
        """
        StockTransaction.objects.create(
            transaction_type=transaction_type,
            stock_item=self,
            quantity=quantity,
            notes=notes,
            branch=self.branch
        )

    def suggest_selling_price(self, profit_margin_percentage):
        profit_margin_percentage=self.branch.business.default_profit_margin
        if profit_margin_percentage is None:
            profit_margin_percentage = 30
        """
        Suggest a selling price based on profit margin percentage.
        """
        return self.buying_price * (1 + Decimal(profit_margin_percentage) / 100)

    def __str__(self):
        return f"{self.product} (qty {self.stock_level})"

    class Meta:
        db_table = 'inventory'
        verbose_name = 'Stock Inventory'
        verbose_name_plural = 'Stock Inventory'
        indexes = [
            models.Index(fields=['product'], name='idx_stock_inventory_product'),
            models.Index(fields=['product_type'], name='idx_stock_inv_product_type'),
            models.Index(fields=['variation'], name='idx_stock_inventory_variation'),
            models.Index(fields=['branch'], name='idx_stock_inventory_branch'),
            models.Index(fields=['supplier'], name='idx_stock_inventory_supplier'),
            models.Index(fields=['availability'], name='idx_stock_inv_availability'),
            models.Index(fields=['is_new_arrival'], name='idx_stock_inv_new_arrival'),
            models.Index(fields=['is_top_pick'], name='idx_stock_inv_top_pick'),
            models.Index(fields=['delete_status'], name='idx_stock_inv_delete_status'),
            models.Index(fields=['created_at'], name='idx_stock_inventory_created_at'),
        ]

class StockTransaction(models.Model):
    TRANSACTION_TYPES = [
        ('INITIAL', 'Opening Stock'),
        ('PURCHASE', 'Purchase'),
        ('SALE', 'Sale'),
        ('SALE_RETURN', 'Sale Return'),
        ('PURCHASE_RETURN', 'Purchase Return'),
        ('ADJUSTMENT', 'Adjustment'),
        ('TRANSFER_IN', 'Transfer In'),
        ('TRANSFER_OUT', 'Transfer Out'),
        ('STOCK_TAKE', 'Stock Take'),
        ('PRODUCTION', 'Production'),
    ]
    branch=models.ForeignKey(Branch,on_delete=models.CASCADE,blank=True,null=True,related_name="stock_transactions")
    transaction_type = models.CharField(max_length=20, choices=TRANSACTION_TYPES)
    transaction_date = models.DateTimeField(auto_now_add=True)
    stock_item = models.ForeignKey(StockInventory, on_delete=models.CASCADE)
    quantity = models.IntegerField(default=0)
    notes = models.TextField(blank=True, null=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL,related_name='stock',null=True,blank=True)
    updated_by = models.ForeignKey(User, on_delete=models.SET_NULL,related_name='stock_updated',null=True,blank=True)

    def save(self, *args, **kwargs):
        # Set created_by and updated_by to the current user if available
        user = kwargs.pop('user', None)
        if user:
            if not self.pk:
                self.created_by = user
            self.updated_by = user
        # add notes to transaction
        if self.notes:
            self.notes = f"{self.notes} - {user.username if user else ''} - {datetime.now()}"
        super().save(*args, **kwargs)

    def __str__(self):
            return f"{self.transaction_type}({self.transaction_date}):{self.stock_item}  (qty {self.quantity})"

    class Meta:
        verbose_name = 'Stock Transactions'
        verbose_name_plural = 'Stock Transactions'
        indexes = [
            models.Index(fields=['branch'], name='idx_stock_transaction_branch'),
            models.Index(fields=['transaction_type'], name='idx_stock_transaction_type'),
            models.Index(fields=['transaction_date'], name='idx_stock_transaction_date'),
            models.Index(fields=['stock_item'], name='idx_stock_trans_item'),
            models.Index(fields=['created_by'], name='idx_stock_trans_created'),
        ]

class StockTransfer(models.Model):
    added_by=models.ForeignKey(User,on_delete=models.SET_NULL,blank=True,null=True,related_name='stock_transfers')
    transfrer_date=models.DateField(auto_now=True)
    ref_no=models.CharField(max_length=100,blank=True,null=True,help_text="Leave blank to auto generate")
    status=models.CharField(max_length=50,choices=[("Pending","Pending"),("In-Transit","In-Transit"),("Completed","Completed")],default='Pending')
    branch_from=models.ForeignKey(Branch,on_delete=models.CASCADE,related_name='transfers_from')
    branch_to=models.ForeignKey(Branch,on_delete=models.CASCADE,related_name='transfers_to')
    tranfer_notes=models.TextField(blank=True,null=True)
    transfer_shipping_charge=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'))
    net_total=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'),help_text="Auto calculated field. Do not fill.")
    purchase_total=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'),help_text="Auto calculated field. Do not fill.")

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if self.ref_no is None or self.ref_no == "":
           self.ref_no=generate_ref_no()
        # Calculate net_total
        self.net_total = self.transfer_items.aggregate(total=Sum('sub_total'))['total'] or 0
        # Calculate purchase_total
        self.purchase_total = self.net_total + self.transfer_shipping_charge
        # Check if the status is being updated to 'Completed'
        if self.pk and self.status == 'Completed':
            # Iterate through transfer items
            for item in self.transfer_items.all():
                # Create new StockInventory entry for the location_to
                if item.quantity < item.stock_item.stock_level:
                    _, created = StockInventory.objects.get_or_create(
                    product=item.stock_item.product,
                    product_type=item.stock_item.product_type,
                    variation=item.stock_item.variation,
                    branch=self.branch_to,
                    defaults={
                        'warranty': item.stock_item.warranty,
                        'discount': item.stock_item.discount,
                        'applicable_tax': item.stock_item.applicable_tax,
                        'buying_price': item.stock_item.buying_price,
                        'selling_price': item.stock_item.selling_price,
                        'stock_level': item.quantity,
                        'reorder_level': item.stock_item.reorder_level,
                        'unit': item.stock_item.unit,
                        'usage': item.stock_item.usage,
                        'supplier': item.stock_item.supplier,
                        'availability': item.stock_item.availability,
                        'is_new_arrival': item.stock_item.is_new_arrival,
                        'is_top_pick': item.stock_item.is_top_pick
                       }
                    )
                    # If the instance already exists, update the stock_level
                    if not created:
                        StockInventory.objects.filter(
                            product=item.stock_item.product,
                            product_type=item.stock_item.product_type,
                            variation=item.stock_item.variation,
                            branch=self.branch_to
                        ).update(
                            stock_level=F('stock_level') + item.quantity
                        )
                    # Subtract transferred quantity from the location_from
                    item.stock_item.stock_level -= item.quantity
                    item.stock_item.save()
            super().save(*args, **kwargs)

    def __str__(self):
        return f"({self.transfrer_date}) From {self.branch_from} to {self.branch_to}:{self.status}"

    class Meta:
        indexes = [
            models.Index(fields=['added_by'], name='idx_stock_transfer_added_by'),
            models.Index(fields=['transfrer_date'], name='idx_stock_transfer_date'),
            models.Index(fields=['ref_no'], name='idx_stock_transfer_ref_no'),
            models.Index(fields=['status'], name='idx_stock_transfer_status'),
            models.Index(fields=['branch_from'], name='idx_stock_transfer_from'),
            models.Index(fields=['branch_to'], name='idx_stock_transfer_branch_to'),
        ]

class StockTransferItem(models.Model):
    stock_transfer=models.ForeignKey(StockTransfer,on_delete=models.CASCADE,related_name='transfer_items')
    stock_item=models.ForeignKey(StockInventory,on_delete=models.CASCADE,related_name='transfer_items')
    quantity=models.PositiveIntegerField(default=1)
    sub_total=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'),help_text="Auto calculated field. Do not fill.")

    def save(self,*args,**kwargs):
        self.sub_total=self.quantity*self.stock_item.buying_price
        super().save(*args,**kwargs)

    def __str__(self) -> str:
        return f"{self.stock_item.product.title} {self.stock_item.variation}"

    class Meta:
        indexes = [
            models.Index(fields=['stock_transfer'], name='idx_stock_transfer_item'),
            models.Index(fields=['stock_item'], name='idx_stock_transfer_item_stock'),
        ]

class StockAdjustment(models.Model):
    ADJUSTMENT_TYPES = [
        ('increase', _('Increase')),
        ('decrease', _('Decrease')),
    ]
    branch=models.ForeignKey(Branch,on_delete=models.CASCADE,related_name='stock_adjustments',blank=True,null=True)
    ref_no=models.CharField(max_length=50,blank=True,null=True,help_text="Leave blank to auto genrate")
    adjusted_by=models.ForeignKey(User,on_delete=models.CASCADE,related_name='stock_adjustments',null=True,blank=True,help_text='Leave blank to pick current logged in user')
    stock_item = models.ForeignKey(StockInventory, on_delete=models.CASCADE, related_name='adjustments')
    adjustment_type = models.CharField(max_length=10, choices=ADJUSTMENT_TYPES)
    quantity_adjusted = models.PositiveIntegerField(default=0)
    total_amount=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'),help_text="Auto calculated field. Do not fill.")
    total_recovered=models.DecimalField(max_digits=14,decimal_places=2,default=Decimal('0.00'),help_text="Total recovered fron insurance, selling item scrap or others")
    adjusted_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True,null=True)

    def save(self, *args, **kwargs):
        self.ref_no=generate_ref_no()
        self.total_amount=self.stock_item.buying_price*self.quantity_adjusted
        # Set adjusted_by to the current logged-in user if available
        if self.branch is None:
            self.branch=self.stock_item.branch
        user = kwargs.pop('user', None)  # Retrieve user from kwargs
        if user and self.adjusted_by is None:
            self.adjusted_by = user
        super().save(*args, **kwargs)
        self.update_stock_level()

    def update_stock_level(self):
        if self.adjustment_type == 'increase':
            self.stock_item.stock_level += self.quantity_adjusted
        elif self.adjustment_type == 'decrease':
            self.stock_item.stock_level -= self.quantity_adjusted
        self.stock_item.save()

    class Meta:
        indexes = [
            models.Index(fields=['branch'], name='idx_stock_adjustment_branch'),
            models.Index(fields=['ref_no'], name='idx_stock_adjustment_ref_no'),
            models.Index(fields=['adjusted_by'], name='idx_stock_adj_by'),
            models.Index(fields=['stock_item'], name='idx_stock_adj_item'),
            models.Index(fields=['adjustment_type'], name='idx_stock_adjustment_type'),
            models.Index(fields=['adjusted_at'], name='idx_stock_adj_at'),
        ]

class ProductView(models.Model):
    stock = models.ForeignKey(StockInventory, on_delete=models.CASCADE)
    viewed_by = models.ForeignKey(User, on_delete=models.CASCADE)
    view_date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.viewed_by} viewed {self.stock} at {self.view_date}"

    class Meta:
        db_table = 'product_views'
        verbose_name = 'Product View'
        verbose_name_plural = 'Product Views'
        indexes = [
            models.Index(fields=['stock'], name='idx_product_view_stock'),
            models.Index(fields=['viewed_by'], name='idx_product_view_viewed_by'),
            models.Index(fields=['view_date'], name='idx_product_view_date'),
        ]
class Favourites(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    stock = models.ForeignKey(
        StockInventory, on_delete=models.CASCADE, related_name='favourites')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "favourites"
        managed = True
        verbose_name_plural = "Favourites"
        unique_together = ('user', 'stock')
        indexes = [
            models.Index(fields=['user'], name='idx_favourites_user'),
            models.Index(fields=['stock'], name='idx_favourites_stock'),
            models.Index(fields=['created_at'], name='idx_favourites_created_at'),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.stock.product.title}"

class Review(models.Model):
    stock = models.ForeignKey(
        StockInventory, on_delete=models.CASCADE, related_name='reviews')
    user = models.ForeignKey(User, on_delete=models.SET_NULL,related_name='images',null=True,blank=True)
    text = models.TextField()
    rating = models.PositiveIntegerField(
        default=0, choices=((5, 5), (4, 4), (3, 3), (2, 2), (1, 1)))
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return str(self.rating)

    class Meta:
        db_table = "reviews"
        managed = True
        verbose_name_plural = "Reviews"
        indexes = [
            models.Index(fields=['stock'], name='idx_reviews_stock'),
            models.Index(fields=['user'], name='idx_reviews_user'),
            models.Index(fields=['rating'], name='idx_reviews_rating'),
            models.Index(fields=['created_at'], name='idx_reviews_created_at'),
        ]