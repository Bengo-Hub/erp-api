from datetime import datetime
from django.db import models
from django.utils import timezone
from django.contrib.auth import get_user_model
from ecommerce.vendor.models import Vendor

User = get_user_model()
# Create your models here.

STATUS_CHOICES = (
    ('active', 'Active'),
    ('inactive', 'Inactive'),
)

class Category(models.Model):
    """
    Unified category model that supports hierarchical categories.
    Uses self-referencing foreign key for parent-child relationships.
    """
    name = models.CharField(max_length=255)
    parent = models.ForeignKey('self', on_delete=models.CASCADE, null=True, blank=True, related_name='children')
    display_image = models.ImageField(upload_to='categories/display/', null=True, blank=True)
    status = models.CharField(default='active', choices=STATUS_CHOICES)
    level = models.PositiveIntegerField(default=0, help_text="Category hierarchy level (0=root, 1=main, 2=sub)")
    order = models.PositiveIntegerField(default=0, help_text="Display order within same level")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Calculate level based on parent
        if self.parent:
            self.level = self.parent.level + 1
        else:
            self.level = 0
        super().save(*args, **kwargs)

    @property
    def is_root(self):
        """Check if this is a root category (no parent)"""
        return self.parent is None

    @property
    def is_main_category(self):
        """Check if this is a main category (level 1)"""
        return self.level == 1

    @property
    def is_subcategory(self):
        """Check if this is a subcategory (level 2 or higher)"""
        return self.level >= 2

    @property
    def get_children(self):
        """Get all direct children"""
        return self.children.all().order_by('order', 'name')

    @property
    def get_all_children(self):
        """Get all descendants recursively"""
        children = []
        for child in self.children.all():
            children.append(child)
            children.extend(child.get_all_children)
        return children

    @property
    def get_ancestors(self):
        """Get all ancestors from root to parent"""
        ancestors = []
        current = self.parent
        while current:
            ancestors.insert(0, current)
            current = current.parent
        return ancestors

    class Meta:
        db_table = "categories"
        ordering = ['level', 'order', 'name']
        managed = True
        verbose_name_plural = "Categories"
        indexes = [
            models.Index(fields=['name'], name='idx_category_name'),
            models.Index(fields=['parent'], name='idx_category_parent'),
            models.Index(fields=['status'], name='idx_category_status'),
            models.Index(fields=['level'], name='idx_category_level'),
            models.Index(fields=['order'], name='idx_category_order'),
            models.Index(fields=['created_at'], name='idx_category_created_at'),
        ]

class ProductImages(models.Model):
    product=models.ForeignKey("Products",on_delete=models.SET_NULL,related_name='images',null=True,blank=True)
    image = models.FileField(upload_to="products/%Y%m%d/")

    def __str__(self):
        return self.image.url if self.image else None

    class Meta:
        db_table = "productimages"
        managed = True
        verbose_name_plural = "Images"
        indexes = [
            models.Index(fields=['product'], name='idx_product_images_product'),
        ]

class ProductBrands(models.Model):
    title=models.CharField(max_length=100)

    def __str__(self):
        return self.title

    class Meta:
        db_table = "brands"
        managed = True
        verbose_name_plural = "Brands"
        indexes = [
            models.Index(fields=['title'], name='idx_product_brands_title'),
        ]

class ProductModels(models.Model):
    title=models.CharField(max_length=100)

    def __str__(self):
        return self.title

    class Meta:
        db_table = "models"
        managed = True
        verbose_name_plural = "Models"
        indexes = [
            models.Index(fields=['title'], name='idx_product_models_title'),
        ]

class Products(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, null=True, blank=True, related_name='products')
    brand = models.ForeignKey(ProductBrands,on_delete=models.SET_NULL,blank=True, null=True,related_name="products")
    model = models.ForeignKey(ProductModels,on_delete=models.SET_NULL,blank=True, null=True,related_name="products")
    title = models.CharField(max_length=500, default="Hp x2 1033")
    serial=models.CharField(max_length=100,blank=True,null=True,unique=True)
    sku=models.CharField(max_length=100,blank=True,null=True,unique=True)
    description = models.TextField(null=True,blank=True)
    status = models.CharField(max_length=10,choices=(('active','Active'),('inactive','Inactive')),default='active')
    date_updated = models.DateTimeField(auto_now=True)
    weight = models.CharField(max_length=255, blank=True, null=True)
    dimentions = models.CharField(max_length=50, default="", blank=True, null=True)
    is_featured = models.BooleanField(default=False)
    is_manufactured = models.BooleanField(default=False)
    view_count = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, null=True)
    updated_at = models.DateTimeField(auto_now=True, null=True)
    seo_title = models.CharField(max_length=100, blank=True, null=True)
    seo_description = models.TextField(blank=True, null=True)
    seo_keywords = models.CharField(max_length=255, blank=True, null=True)

    def __str__(self):
        return self.title

    class Meta:
        db_table = 'products'
        managed = True
        verbose_name = 'Products'
        verbose_name_plural = 'Products'
        indexes = [
            models.Index(fields=['title'], name='idx_product_title'),
            models.Index(fields=['serial'], name='idx_product_serial'),
            models.Index(fields=['sku'], name='idx_product_sku'),
            models.Index(fields=['status'], name='idx_product_status'),
            models.Index(fields=['is_featured'], name='idx_product_featured'),
            models.Index(fields=['category'], name='idx_product_category'),
            models.Index(fields=['brand'], name='idx_product_brand'),
            models.Index(fields=['created_at'], name='idx_product_created_at'),
        ]

    def product_total(self):
        return self.title

